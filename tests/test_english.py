import json
from datetime import UTC, datetime
from threading import Barrier

import httpx
import pytest

from data_pipeline.datasets import DatasetMergeError, merge_datasets
from data_pipeline.english import GeminiTranslator, enrich_english, validate_response
from data_pipeline.identifiers import sha256_text, stable_id
from data_pipeline.ml_evidence import export_ml_evidence, validate_ml_evidence
from data_pipeline.models import Book, CanonicalDataset, Document, Source, TocEntry
from data_pipeline.storage import read_dataset, write_dataset


def fixture_dataset(count=1):
    books, sources, toc, documents = [], [], [], []
    for i in range(count):
        book = Book(
            book_id=stable_id("book", str(i)),
            title="선형대수",
            language="ko",
            topics=["linear-algebra"],
            authors=["원저자"],
        )
        source = Source(
            source_id=f"source-{i}",
            book_id=book.book_id,
            provider="fixture",
            source_type="metadata_api",
            url="https://example.test",
            retrieved_at=datetime(2026, 10, 2, tzinfo=UTC),
            content_hash=sha256_text("원문"),
        )
        books.append(book)
        sources.append(source)
        toc.append(
            TocEntry(
                toc_entry_id=f"toc-{i}",
                book_id=book.book_id,
                title="행렬",
                level=1,
                order_index=0,
                source_id=source.source_id,
            )
        )
        documents.append(
            Document(
                document_id=f"doc-{i}",
                book_id=book.book_id,
                document_type="description",
                text="행렬과 벡터를 설명합니다.",
                source_id=source.source_id,
                content_hash=sha256_text("행렬과 벡터를 설명합니다."),
            )
        )
    return CanonicalDataset(books=books, sources=sources, toc=toc, documents=documents)


class FakeTranslator:
    model = "fixture-model"

    def __init__(self, barrier=None):
        self.calls = []
        self.barrier = barrier

    def translate(self, payload):
        self.calls.append(payload)
        if self.barrier:
            self.barrier.wait(timeout=5)
        return {item["id"]: "Matrices and vectors" for item in payload["items"]}, {
            "input_tokens": 10,
            "output_tokens": 20,
            "total_tokens": 30,
        }


def test_bounded_toc_batches_resume_without_retranslating_or_changing_originals(tmp_path):
    source, output = tmp_path / "source", tmp_path / "english"
    write_dataset(fixture_dataset(3), source)
    original = {p.name: p.read_bytes() for p in source.iterdir()}
    translator = FakeTranslator()
    results = [
        enrich_english(source, output, translator, scope="toc", max_new_requests=1)
        for _ in range(3)
    ]
    assert [len(r["pending_books"]) for r in results] == [2, 1, 0]
    assert all(r["api_requests"] == 1 and not r["failures"] for r in results)
    assert len(translator.calls) == 3
    assert all(t.en_title == "Matrices and vectors" for t in read_dataset(output).toc)
    assert original == {p.name: p.read_bytes() for p in source.iterdir()}
    assert (
        enrich_english(source, output, translator, scope="toc", max_new_requests=1)["api_requests"]
        == 0
    )


def test_parallel_enrichment_preserves_sources_and_replays_without_api(tmp_path):
    original = fixture_dataset(2)
    source_dir, target = tmp_path / "original", tmp_path / "english"
    write_dataset(original, source_dir)
    before = {p.name: p.read_bytes() for p in source_dir.iterdir()}
    translator = FakeTranslator(Barrier(2))
    summary = enrich_english(source_dir, target, translator, workers=2)
    assert summary["completed_books"] == 2
    assert summary["api_requests"] == 2
    assert summary["input_tokens"] == 20
    enriched = read_dataset(target)
    assert enriched.books[0].title == "선형대수"
    assert enriched.books[0].en_title == "Matrices and vectors"
    assert enriched.books[0].language == "ko"
    assert enriched.toc[0].title == "행렬"
    assert enriched.toc[0].en_title == "Matrices and vectors"
    assert enriched.documents[0].en_text
    assert enriched.sources == original.sources
    assert before == {p.name: p.read_bytes() for p in source_dir.iterdir()}
    exported = export_ml_evidence(enriched, contract_version="book-evidence-v3")
    assert validate_ml_evidence(exported, enriched) == []
    assert all(
        item.en_text
        for book in exported
        for item in book.evidence
        if item.evidence_type != "subject"
    )
    prepared = {p.name: p.read_bytes() for p in target.glob("*.jsonl")}
    repeated = enrich_english(source_dir, target, FakeTranslator(), workers=2)
    assert repeated["api_requests"] == 0
    assert repeated["cached_requests"] == 2
    assert repeated["total_tokens"] == 0
    assert prepared == {p.name: p.read_bytes() for p in target.glob("*.jsonl")}


def test_no_english_fields_added_to_legacy_serialization():
    dataset = fixture_dataset()
    assert "en_title" not in dataset.books[0].model_dump()
    assert "en_text" not in dataset.documents[0].model_dump()


def test_toc_scope_does_not_send_book_descriptions(tmp_path):
    source, target = tmp_path / "original", tmp_path / "english"
    write_dataset(fixture_dataset(), source)
    translator = FakeTranslator()
    result = enrich_english(source, target, translator, scope="toc")
    assert result["completed_books"] == 1
    assert translator.calls
    for payload in translator.calls:
        assert all(item["id"].startswith("toc:") for item in payload["items"])
        assert "행렬과 벡터를 설명합니다." not in json.dumps(payload, ensure_ascii=False)
    enriched = read_dataset(target)
    assert enriched.books[0].en_title is None
    assert enriched.documents[0].en_text is None
    assert enriched.toc[0].en_title == "Matrices and vectors"


def english_dataset():
    dataset = fixture_dataset()
    dataset.books[0].title = "Linear Algebra"
    dataset.books[0].language = "en"
    dataset.toc[0].title = "Matrices"
    dataset.documents[0].text = ("Matrices and vectors are discussed here. " * 200).strip()
    dataset.documents[0].content_hash = sha256_text(dataset.documents[0].text)
    return dataset


def test_english_copy_needs_no_key_or_api_and_preserves_long_text(tmp_path, monkeypatch):
    dataset = english_dataset()
    dataset.toc[0].title = "  Matrices \n"
    source, target = tmp_path / "original", tmp_path / "english"
    write_dataset(dataset, source)
    translator = GeminiTranslator("")

    def never_send(*args, **kwargs):
        raise AssertionError("English copy must not call Gemini")

    monkeypatch.setattr(translator.client, "post", never_send)
    try:
        summary = enrich_english(source, target, translator, chunk_chars=500)
    finally:
        translator.close()
    result = read_dataset(target)
    assert summary["planned_requests"] == summary["api_requests"] == 0
    assert summary["provider_attempts"] == 0
    assert summary["completed_books"] == 1
    assert result.books[0].en_title == dataset.books[0].title
    assert result.toc[0].en_title == dataset.toc[0].title
    assert result.documents[0].en_text == dataset.documents[0].text
    assert result.documents[0].content_hash == dataset.documents[0].content_hash
    assert (
        validate_ml_evidence(
            export_ml_evidence(result, contract_version="book-evidence-v3"), result
        )
        == []
    )


def test_mixed_languages_at_same_provider_only_translate_korean(tmp_path):
    english, korean = english_dataset(), fixture_dataset(2)
    korean = CanonicalDataset(
        books=korean.books[1:],
        documents=korean.documents[1:],
        toc=korean.toc[1:],
        sources=korean.sources[1:],
    )
    # An English heading from the Korean record also takes the copy path.
    korean.toc[0].title = "Vectors"
    source, target = tmp_path / "original", tmp_path / "english"
    write_dataset(merge_datasets([english, korean]), source)
    translator = FakeTranslator()
    summary = enrich_english(source, target, translator)
    assert summary["completed_books"] == 2
    assert len(translator.calls) == 1
    ids = {item["id"] for item in translator.calls[0]["items"]}
    assert ids == {f"book:{korean.books[0].book_id}:en_title:0", "doc:doc-1:en_text:0"}
    result = read_dataset(target)
    assert next(t for t in result.toc if t.toc_entry_id == "toc-1").en_title == "Vectors"


def test_merge_fills_english_partial_evidence_from_book_language():
    dataset = english_dataset()
    metadata = CanonicalDataset(books=dataset.books, documents=[], toc=[], sources=dataset.sources)
    evidence = CanonicalDataset(books=[], documents=dataset.documents, toc=dataset.toc, sources=[])
    result = merge_datasets([metadata, evidence])
    assert result.books[0].en_title == dataset.books[0].title
    assert result.toc[0].en_title == dataset.toc[0].title
    assert result.documents[0].en_text == dataset.documents[0].text
    assert dataset.books[0].en_title is None
    assert dataset.documents[0].en_text is None


def test_merge_preserves_existing_translations_and_rejects_conflicts():
    original = fixture_dataset()
    translated = original.model_copy(deep=True)
    translated.books[0].en_title = "Linear Algebra"
    translated.toc[0].en_title = "Matrices"
    translated.documents[0].en_text = "Matrices and vectors"
    first = merge_datasets([original, translated])
    assert first == merge_datasets([translated, original])
    assert first.books[0].en_title == "Linear Algebra"
    assert first.documents[0].en_text == "Matrices and vectors"
    changed = translated.model_copy(deep=True)
    changed.toc[0].en_title = "Determinants"
    with pytest.raises(DatasetMergeError, match="toc_entry_id"):
        merge_datasets([translated, changed])


def test_missing_key_blocks_only_requests_that_need_translation(tmp_path):
    source, target = tmp_path / "original", tmp_path / "english"
    write_dataset(fixture_dataset(), source)
    translator = GeminiTranslator("")
    try:
        result = enrich_english(source, target, translator)
    finally:
        translator.close()
    assert result["provider_attempts"] == 0
    assert result["completed_books"] == 0
    assert result["failures"][0]["reason"] == "missing_translation_api_key"
    assert read_dataset(target).books[0].en_title is None


@pytest.mark.parametrize(
    "rows",
    [
        [{"id": "a", "text": "Matrices"}, {"id": "a", "text": "Vectors"}],
        [{"id": "b", "text": "Matrices"}],
        [{"id": "a", "text": "행렬"}],
        [{"id": "a", "text": " "}],
    ],
)
def test_invalid_translation_is_not_published(rows):
    with pytest.raises(ValueError):
        validate_response({"translations": rows}, [{"id": "a"}])


def test_failed_book_remains_untranslated_and_dry_run_calls_no_api(tmp_path):
    source, target = tmp_path / "original", tmp_path / "english"
    write_dataset(fixture_dataset(), source)

    class Broken(FakeTranslator):
        def translate(self, payload):
            raise ValueError("provider failure")

    result = enrich_english(source, target, Broken())
    assert result["completed_books"] == 0
    assert len(result["failures"]) == 1
    assert read_dataset(target).books[0].en_title is None
    fake = FakeTranslator()
    dry = enrich_english(source, tmp_path / "dry", fake, dry_run=True)
    assert dry["planned_requests"] == 1
    assert fake.calls == []
    assert not (tmp_path / "dry").exists()
    with pytest.raises(ValueError, match="differ"):
        enrich_english(source, source, fake)


def test_modified_source_does_not_reuse_previous_translation(tmp_path):
    source, target = tmp_path / "original", tmp_path / "english"
    original = fixture_dataset()
    write_dataset(original, source)
    enrich_english(source, target, FakeTranslator())
    original.toc[0].title = "固有値"
    write_dataset(original, source)
    fake = FakeTranslator()
    assert enrich_english(source, target, fake)["api_requests"] == 1


def test_provider_json_contract_and_billable_thinking_tokens():
    translator = GeminiTranslator("fixture-secret")

    def reply(request):
        assert request.headers["x-goog-api-key"] == "fixture-secret"
        payload = json.loads(request.content)
        assert payload["generationConfig"]["thinkingConfig"]["thinkingLevel"] == "minimal"
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {
                            "parts": [{"text": '{"translations":[{"id":"a","text":"Matrices"}]}'}]
                        },
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 10,
                    "candidatesTokenCount": 20,
                    "thoughtsTokenCount": 5,
                    "totalTokenCount": 35,
                },
            },
        )

    translator.client.close()
    translator.client = httpx.Client(
        transport=httpx.MockTransport(reply),
        base_url="https://example.test",
        headers={"x-goog-api-key": "fixture-secret"},
    )
    result, usage = translator.translate({"items": [{"id": "a", "text": "행렬"}]})
    assert result == {"a": "Matrices"}
    assert usage["output_tokens"] == 25
    assert translator.usage_totals["total_tokens"] == 35
    translator.close()
