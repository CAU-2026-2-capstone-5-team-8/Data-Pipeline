from datetime import UTC, datetime

import pytest
from typer.testing import CliRunner

from data_pipeline.cli import app
from data_pipeline.identifiers import sha256_text, stable_id
from data_pipeline.ml_evidence import (
    MlEvidenceItem,
    evidence_provenance_hash,
    export_ml_evidence,
    read_ml_evidence,
    summarize_ml_evidence,
    validate_ml_evidence,
    write_ml_evidence,
)
from data_pipeline.models import (
    Book,
    CanonicalDataset,
    Document,
    EvidenceProvenance,
    Source,
    TocEntry,
)
from data_pipeline.storage import write_dataset


def _book(slug: str, title: str) -> Book:
    return Book(
        book_id=stable_id("book", slug),
        title=title,
        authors=["Fixture Author"],
        language="en",
        topics=["computer-science", "operating-systems"],
    )


def _source(
    book: Book,
    slug: str,
    *,
    source_type: str = "metadata_api",
    evidence: EvidenceProvenance | None = None,
) -> Source:
    return Source(
        source_id=stable_id("source", slug),
        book_id=book.book_id,
        provider=slug.split("-")[0],
        source_type=source_type,
        url=f"https://example.test/{slug}",
        retrieved_at=datetime(2026, 9, 22, tzinfo=UTC),
        content_hash=sha256_text(f"source:{slug}"),
        evidence=evidence,
    )


def _toc_provenance(book: Book, tier: str, *, same_edition: bool) -> EvidenceProvenance:
    return EvidenceProvenance(
        evidence_type="toc",
        tier=tier,
        target_title=book.title,
        target_authors=book.authors,
        source_edition_id="OL1M",
        source_title=book.title,
        same_edition=same_edition,
        source_document_type=(
            "public_html" if tier == "validated_public_web_toc" else "open_library_dump"
        ),
        discovery_method="fixture",
        match_basis=["provider_work_relation" if not same_edition else "exact_title_author"],
        validation_status="strong",
    )


def _dataset() -> CanonicalDataset:
    exact = _book("exact", "Exact Textbook")
    public = _book("public", "Public Web Textbook")
    alternate = _book("alternate", "Alternate Edition Textbook")
    metadata = _book("metadata", "Metadata-only Textbook")

    metadata_sources = [
        _source(book, f"metadata-{index}")
        for index, book in enumerate((exact, public, alternate, metadata))
    ]
    exact_source = _source(
        exact,
        "openlibrary-exact",
        evidence=_toc_provenance(exact, "exact_edition_toc", same_edition=True),
    )
    public_source = _source(
        public,
        "publisher-public",
        source_type="publisher_page",
        evidence=_toc_provenance(public, "validated_public_web_toc", same_edition=True),
    )
    alternate_source = _source(
        alternate,
        "openlibrary-alternate",
        evidence=_toc_provenance(
            alternate,
            "same_work_alternate_edition_toc",
            same_edition=False,
        ),
    )
    toc_sources = [exact_source, public_source, alternate_source]
    toc = []
    for index, (book, source) in enumerate(
        zip((exact, public, alternate), toc_sources, strict=True)
    ):
        root_id = stable_id("toc", str(index), "root")
        toc.extend(
            [
                TocEntry(
                    toc_entry_id=root_id,
                    book_id=book.book_id,
                    level=1,
                    order_index=0,
                    label="1",
                    title="Memory",
                    source_id=source.source_id,
                ),
                TocEntry(
                    toc_entry_id=stable_id("toc", str(index), "child"),
                    book_id=book.book_id,
                    parent_entry_id=root_id,
                    level=2,
                    order_index=0,
                    label="1.1",
                    title="Virtual Memory",
                    source_id=source.source_id,
                ),
            ]
        )
    description_source = metadata_sources[-1]
    document = Document(
        document_id=stable_id("doc", "metadata-description"),
        book_id=metadata.book_id,
        document_type="description",
        text="A verified publisher-independent description.",
        source_id=description_source.source_id,
        content_hash=sha256_text("metadata description"),
    )
    return CanonicalDataset(
        books=[metadata, alternate, exact, public],
        documents=[document],
        toc=list(reversed(toc)),
        sources=[*metadata_sources, *toc_sources],
    )


def test_exports_evidence_categories_without_numeric_confidence() -> None:
    dataset = _dataset()
    records = export_ml_evidence(dataset)
    by_title = {record.book.title: record for record in records}

    assert validate_ml_evidence(records, dataset) == []
    assert {item.evidence_type for item in by_title["Exact Textbook"].evidence} >= {"toc_exact"}
    assert {item.evidence_type for item in by_title["Public Web Textbook"].evidence} >= {
        "toc_public_web_exact"
    }
    alternate = by_title["Alternate Edition Textbook"].evidence
    assert {item.evidence_type for item in alternate} >= {"toc_same_work"}
    assert {
        item.edition_relation for item in alternate if item.evidence_type == "toc_same_work"
    } == {"same_work"}
    metadata = by_title["Metadata-only Textbook"].evidence
    assert {item.evidence_type for item in metadata} == {
        "description",
        "metadata_minimal",
        "subject",
    }
    assert all("confidence" not in item.model_dump() for item in metadata)


def test_preserves_toc_paths_and_never_labels_description_as_toc() -> None:
    records = export_ml_evidence(_dataset())
    paths = [
        item.toc_path
        for record in records
        for item in record.evidence
        if item.text == "Virtual Memory"
    ]
    description = next(
        item
        for record in records
        for item in record.evidence
        if item.evidence_type == "description"
    )

    assert paths == [["Memory", "Virtual Memory"]] * 3
    assert description.toc_entry_id is None
    assert description.document_id is not None


def test_summary_counts_unique_books_and_zero_empty_records() -> None:
    records = export_ml_evidence(_dataset())
    summary = summarize_ml_evidence(records, [])

    assert summary["total_books"] == 4
    assert summary["books_with_toc_evidence"] == 3
    assert summary["books_with_exact_toc"] == 2
    assert summary["books_with_same_work_alternate_toc"] == 1
    assert summary["books_with_public_web_toc"] == 1
    assert summary["metadata_fallback_only"] == 1
    assert summary["books_with_zero_evidence"] == 0


def test_deterministic_output_and_provenance_hash(tmp_path) -> None:
    dataset = _dataset()
    first = export_ml_evidence(dataset)
    second = export_ml_evidence(dataset)
    first_path = tmp_path / "first.jsonl"
    second_path = tmp_path / "second.jsonl"

    write_ml_evidence(first, first_path)
    write_ml_evidence(second, second_path)

    assert first_path.read_bytes() == second_path.read_bytes()
    assert read_ml_evidence(first_path) == first
    assert all(
        evidence_provenance_hash(item) == item.provenance_hash
        for record in first
        for item in record.evidence
    )


def test_validation_rejects_cross_book_source_and_duplicate_evidence() -> None:
    dataset = _dataset()
    records = export_ml_evidence(dataset)
    first, second = records[:2]
    contaminated = first.evidence[0].model_copy(update={"source_id": second.evidence[0].source_id})
    records[0] = first.model_copy(
        update={"evidence": [contaminated, contaminated, *first.evidence[1:]]}
    )

    errors = validate_ml_evidence(records, dataset)

    assert any("owned by" in error for error in errors)
    assert any("duplicate ML evidence ID" in error for error in errors)
    assert any("deterministic canonical projection" in error for error in errors)


def test_rejects_provenance_type_that_conflicts_with_category() -> None:
    records = export_ml_evidence(_dataset())
    toc = next(
        item
        for record in records
        for item in record.evidence
        if item.evidence_type == "toc_public_web_exact"
    )
    payload = toc.model_dump(mode="json")
    payload["source_evidence"]["evidence_type"] = "metadata"

    with pytest.raises(ValueError, match="type does not match evidence category"):
        MlEvidenceItem.model_validate(payload)


@pytest.mark.parametrize("foreign_field", ["toc_path", "document_content_hash"])
def test_rejects_fields_from_another_evidence_category(foreign_field: str) -> None:
    records = export_ml_evidence(_dataset())
    subject = next(
        item for record in records for item in record.evidence if item.evidence_type == "subject"
    )
    payload = subject.model_dump(mode="json")
    payload[foreign_field] = (
        ["Not a subject path"] if foreign_field == "toc_path" else "sha256:" + "f" * 64
    )

    with pytest.raises(ValueError, match="metadata evidence cannot carry"):
        MlEvidenceItem.model_validate(payload)


def test_validation_rejects_empty_artifact() -> None:
    empty = CanonicalDataset(books=[], documents=[], toc=[], sources=[])

    assert validate_ml_evidence([], empty) == ["ML evidence artifact has zero books"]


@pytest.mark.parametrize(
    "supplement_title",
    [
        "Systems Textbook Student Solutions Manual",
        "Systems Textbook Workbook",
        "Systems Textbook Study Guide",
    ],
)
def test_supplement_remains_a_separate_book(supplement_title: str) -> None:
    textbook = _book("textbook", "Systems Textbook")
    manual = _book("manual", supplement_title)
    textbook_source = _source(textbook, "metadata-textbook")
    manual_source = _source(manual, "metadata-manual")
    dataset = CanonicalDataset(
        books=[textbook, manual],
        documents=[],
        toc=[],
        sources=[textbook_source, manual_source],
    )

    records = export_ml_evidence(dataset)
    textbook_record = next(record for record in records if record.book == textbook)

    assert {item.source_id for item in textbook_record.evidence} == {textbook_source.source_id}
    assert all(supplement_title not in item.text for item in textbook_record.evidence)


def test_cli_exports_valid_byte_stable_artifact(tmp_path) -> None:
    dataset_dir = tmp_path / "canonical"
    output = tmp_path / "export" / "book-evidence.jsonl"
    report = tmp_path / "export" / "summary.json"
    write_dataset(_dataset(), dataset_dir)
    runner = CliRunner()
    args = [
        "export-ml-evidence",
        "--dataset-dir",
        str(dataset_dir),
        "--output",
        str(output),
        "--report",
        str(report),
    ]

    first = runner.invoke(app, args)
    assert first.exit_code == 0, first.output
    first_bytes = output.read_bytes()
    second = runner.invoke(app, args)

    assert second.exit_code == 0, second.output
    assert output.read_bytes() == first_bytes
    assert len(read_ml_evidence(output)) == 4
    assert '"books_with_zero_evidence": 0' in report.read_text(encoding="utf-8")
