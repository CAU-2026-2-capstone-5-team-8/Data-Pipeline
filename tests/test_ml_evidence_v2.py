"""Contract fixture shared byte-for-byte with ML; all text is synthetic."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from data_pipeline.cli import app
from data_pipeline.identifiers import sha256_text
from data_pipeline.ml_evidence import (
    evidence_provenance_hash,
    export_ml_evidence,
    read_ml_evidence,
    validate_ml_evidence,
    write_ml_evidence,
)
from data_pipeline.models import Book, CanonicalDataset, Document, Source, TextExtent
from data_pipeline.storage import write_dataset

FIXTURE = Path(__file__).parent / "fixtures" / "book-evidence-v2.jsonl"


def contract_dataset():
    book = Book(
        book_id="book_11111111111111111111",
        title="Synthetic Linear Algebra",
        authors=["Fixture Author"],
        language="en",
        topics=["linear-algebra"],
    )
    source = Source(
        source_id="source_fixture",
        book_id=book.book_id,
        provider="fixture",
        source_type="publisher_page",
        url="https://example.test/book",
        retrieved_at=datetime(2026, 10, 3, tzinfo=UTC),
        external_id="fixture-edition",
        license=None,
        rights_note="Synthetic test source. No reuse permission inferred.",
        content_hash=sha256_text("synthetic source"),
    )
    documents = []
    for name, kind, extent in [
        ("excerpt", "preface", TextExtent(scope="excerpt", basis="Explicit excerpt label.")),
        (
            "complete",
            "sample_chapter",
            TextExtent(scope="complete_section", basis="Section boundaries verified."),
        ),
        ("unknown", "introduction", None),
    ]:
        text = f"Synthetic {name} document: vectors and matrices are discussed here."
        documents.append(
            Document(
                document_id="doc_" + name,
                book_id=book.book_id,
                document_type=kind,
                text=text,
                source_id=source.source_id,
                content_hash=sha256_text(text),
                text_extent=extent,
            )
        )
    return CanonicalDataset(books=[book], sources=[source], documents=documents, toc=[])


def test_shared_v2_contract_is_stable_and_retains_document_and_source_metadata(tmp_path):
    dataset = contract_dataset()
    records = export_ml_evidence(dataset, "book-evidence-v2")
    assert validate_ml_evidence(records, dataset) == []
    path = tmp_path / "v2.jsonl"
    write_ml_evidence(records, path)
    assert path.read_bytes() == FIXTURE.read_bytes()
    assert read_ml_evidence(path) == records
    docs = {item.document_id: item for item in records[0].evidence if item.document_id}
    assert docs["doc_excerpt"].text_extent.scope == "excerpt"
    assert docs["doc_complete"].text_extent.scope == "complete_section"
    assert docs["doc_unknown"].text_extent is None
    assert all(i.source_rights_note == dataset.sources[0].rights_note for i in records[0].evidence)
    assert all(i.source_license is None for i in records[0].evidence)


def test_explicit_extent_cannot_be_silently_downgraded_to_v1():
    with pytest.raises(ValueError, match="book-evidence-v2"):
        export_ml_evidence(contract_dataset())


def test_cli_requires_v2_before_writing_explicit_extent(tmp_path):
    canonical = tmp_path / "canonical"
    write_dataset(contract_dataset(), canonical)
    output = tmp_path / "export/evidence.jsonl"
    args = ["export-ml-evidence", "--dataset-dir", str(canonical), "--output", str(output)]
    runner = CliRunner()
    refused = runner.invoke(app, args)
    assert refused.exit_code != 0
    assert "book-evidence-v2" in refused.output
    assert not output.exists()
    accepted = runner.invoke(app, [*args, "--contract-version", "book-evidence-v2"])
    assert accepted.exit_code == 0, accepted.output
    assert output.read_bytes() == FIXTURE.read_bytes()


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_license", "invented license"),
        ("source_rights_note", "different rights"),
        ("text_extent", TextExtent(scope="complete_section", basis="unsupported completion claim")),
    ],
)
def test_recomputed_hash_does_not_hide_departure_from_canonical_metadata(field, value):
    dataset = contract_dataset()
    records = export_ml_evidence(dataset, "book-evidence-v2")
    index = next(
        i for i, item in enumerate(records[0].evidence) if item.document_id == "doc_excerpt"
    )
    item = records[0].evidence[index].model_copy(update={field: value})
    item = item.model_copy(update={"provenance_hash": evidence_provenance_hash(item)})
    records[0].evidence[index] = item
    assert any(
        "deterministic canonical projection" in e for e in validate_ml_evidence(records, dataset)
    )


def test_extent_requires_basis_and_never_infers_unknown_documents():
    with pytest.raises(ValueError):
        TextExtent(scope="excerpt", basis="   ")
    document = contract_dataset().documents[-1]
    assert "text_extent" not in document.model_dump()
    assert document.text_extent is None
