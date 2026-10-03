from datetime import UTC, datetime
from pathlib import Path

import pytest

from data_pipeline.identifiers import sha256_text
from data_pipeline.ml_evidence import (
    export_ml_evidence,
    read_ml_evidence,
    validate_ml_evidence,
    write_ml_evidence,
)
from data_pipeline.models import Book, CanonicalDataset, Document, Source, TextExtent, TocEntry

FIXTURE = Path(__file__).parent / "fixtures/book-evidence-v3.jsonl"


def english_dataset():
    book = Book(
        book_id="book_11111111111111111111",
        title="합성 선형대수",
        en_title="Synthetic Linear Algebra",
        authors=["Fixture"],
        language="ko",
        topics=["linear-algebra"],
    )
    source = Source(
        source_id="source_fixture",
        book_id=book.book_id,
        provider="fixture",
        source_type="publisher_page",
        url="https://example.test/book",
        retrieved_at=datetime(2026, 10, 3, tzinfo=UTC),
        content_hash=sha256_text("synthetic"),
        rights_note="Synthetic fixture; no permission inferred.",
    )
    text = " \n합성 문서입니다. 실제 도서 원문이 아닙니다.\n "
    doc = Document(
        document_id="doc_excerpt",
        book_id=book.book_id,
        document_type="preface",
        text=text,
        en_text=" \nSynthetic vectors and matrices.\n ",
        source_id=source.source_id,
        content_hash=sha256_text(text),
        text_extent=TextExtent(scope="excerpt", basis="Synthetic excerpt marker."),
    )
    toc = [
        TocEntry(
            toc_entry_id=f"toc_{i}",
            book_id=book.book_id,
            level=1,
            order_index=i,
            title=title,
            en_title=english,
            source_id=source.source_id,
        )
        for i, title, english in [(0, "행렬", "Matrices"), (1, "벡터", None)]
    ]
    return CanonicalDataset(books=[book], sources=[source], documents=[doc], toc=toc)


def test_shared_v3_roundtrip_preserves_original_whitespace_extent_and_english(tmp_path):
    dataset = english_dataset()
    records = export_ml_evidence(dataset, "book-evidence-v3")
    assert validate_ml_evidence(records, dataset) == []
    output = tmp_path / "v3.jsonl"
    write_ml_evidence(records, output)
    assert output.read_bytes() == FIXTURE.read_bytes()
    assert read_ml_evidence(output) == records
    doc = next(e for e in records[0].evidence if e.document_id)
    assert doc.text == dataset.documents[0].text
    assert doc.en_text == dataset.documents[0].en_text
    assert doc.text_extent.scope == "excerpt"
    assert next(e for e in records[0].evidence if e.toc_entry_id == "toc_1").en_text is None


@pytest.mark.parametrize("version", ["book-evidence-v1", "book-evidence-v2"])
def test_english_fields_cannot_be_silently_downgraded(version):
    with pytest.raises(ValueError, match="book-evidence-v3"):
        export_ml_evidence(english_dataset(), version)


def test_whitespace_and_absent_fields_remain_exact():
    doc = english_dataset().documents[0]
    assert Document.model_validate_json(doc.model_dump_json()).en_text == doc.en_text
    assert "en_text" not in doc.model_copy(update={"en_text": None}).model_dump()
    with pytest.raises(ValueError, match="blank"):
        Document.model_validate({**doc.model_dump(), "en_text": "  \n "})


def test_modified_english_fails_canonical_projection_even_with_valid_hash():
    from data_pipeline.ml_evidence import evidence_provenance_hash

    dataset = english_dataset()
    records = export_ml_evidence(dataset, "book-evidence-v3")
    item = records[0].evidence[0].model_copy(update={"en_text": "unrelated translation"})
    records[0].evidence[0] = item.model_copy(
        update={"provenance_hash": evidence_provenance_hash(item)}
    )
    assert any("canonical projection" in e for e in validate_ml_evidence(records, dataset))
