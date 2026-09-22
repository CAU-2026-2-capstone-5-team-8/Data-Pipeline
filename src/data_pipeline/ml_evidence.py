"""Provider-independent, deterministic evidence handoff for downstream ML."""

import json
import os
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from data_pipeline.identifiers import sha256_json, stable_id
from data_pipeline.models import (
    Book,
    CanonicalDataset,
    CanonicalModel,
    Document,
    DocumentType,
    EvidenceProvenance,
    EvidenceTier,
    Source,
    SourceType,
    TocEntry,
)

CONTRACT_VERSION = "book-evidence-v1"
TocEvidenceType = Literal["toc_exact", "toc_same_work", "toc_public_web_exact"]
MlEvidenceType = Literal[
    "toc_exact",
    "toc_same_work",
    "toc_public_web_exact",
    "description",
    "document",
    "subject",
    "metadata_minimal",
]
EditionRelation = Literal["exact", "same_work", "canonical_record", "unspecified"]


class MlEvidenceItem(CanonicalModel):
    """One collected evidence unit with source and edition provenance."""

    evidence_id: str = Field(pattern=r"^evidence_[0-9a-f]{20}$")
    evidence_type: MlEvidenceType
    text: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    source_type: SourceType
    source_url: str = Field(min_length=1)
    source_retrieved_at: datetime
    source_content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    source_evidence_tier: EvidenceTier | None = None
    source_evidence: EvidenceProvenance | None = None
    edition_relation: EditionRelation
    provenance_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    toc_entry_id: str | None = None
    parent_entry_id: str | None = None
    level: int | None = Field(default=None, ge=1)
    order_index: int | None = Field(default=None, ge=0)
    label: str | None = None
    toc_path: list[str] | None = None
    document_id: str | None = None
    document_type: DocumentType | None = None
    document_content_hash: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    metadata_field: Literal["title", "topics"] | None = None

    @field_validator("text")
    @classmethod
    def text_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("evidence text must not be blank")
        return value

    @field_validator("source_retrieved_at")
    @classmethod
    def retrieval_time_must_include_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("source_retrieved_at must include a timezone")
        return value

    @model_validator(mode="after")
    def type_specific_fields_must_be_consistent(self) -> "MlEvidenceItem":
        if self.source_evidence is not None:
            if self.source_evidence_tier != self.source_evidence.tier:
                raise ValueError("source evidence tier does not match provenance")
            expected_provenance_type = (
                "toc"
                if self.evidence_type.startswith("toc_")
                else "metadata"
                if self.evidence_type in {"subject", "metadata_minimal"}
                else None
            )
            if (
                expected_provenance_type is not None
                and self.source_evidence.evidence_type != expected_provenance_type
            ):
                raise ValueError("source evidence type does not match evidence category")
        elif self.source_evidence_tier is not None:
            raise ValueError("source evidence tier requires source evidence provenance")

        toc_fields = (
            self.toc_entry_id,
            self.parent_entry_id,
            self.level,
            self.order_index,
            self.label,
            self.toc_path,
        )
        document_fields = (
            self.document_id,
            self.document_type,
            self.document_content_hash,
        )
        if self.evidence_type.startswith("toc_"):
            if self.toc_entry_id is None or self.level is None or not self.toc_path:
                raise ValueError("TOC evidence requires entry identity, level, and path")
            if (
                any(value is not None for value in document_fields)
                or self.metadata_field is not None
            ):
                raise ValueError("TOC evidence cannot carry document or metadata identity")
        elif self.evidence_type in {"description", "document"}:
            if (
                self.document_id is None
                or self.document_type is None
                or self.document_content_hash is None
            ):
                raise ValueError("document evidence requires document identity and type")
            if any(value is not None for value in toc_fields) or self.metadata_field is not None:
                raise ValueError("document evidence cannot carry TOC or metadata identity")
        else:
            if self.metadata_field is None:
                raise ValueError("metadata evidence requires a metadata field")
            if any(value is not None for value in (*toc_fields, *document_fields)):
                raise ValueError("metadata evidence cannot carry TOC or document identity")
            if self.evidence_type == "subject" and self.metadata_field != "topics":
                raise ValueError("subject evidence must identify the topics field")
            if self.evidence_type == "metadata_minimal" and self.metadata_field != "title":
                raise ValueError("minimal metadata evidence must identify the title field")
        return self


class MlBookEvidence(CanonicalModel):
    """All normalized evidence available for one canonical book."""

    schema_version: Literal[1] = 1
    contract_version: Literal["book-evidence-v1"] = CONTRACT_VERSION
    book: Book
    book_content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    evidence: list[MlEvidenceItem] = Field(min_length=1)


def _provenance_payload(item: MlEvidenceItem | dict[str, Any]) -> dict[str, Any]:
    payload = item.model_dump(mode="json") if isinstance(item, MlEvidenceItem) else dict(item)
    payload.pop("evidence_id", None)
    payload.pop("provenance_hash", None)
    return payload


def evidence_provenance_hash(item: MlEvidenceItem | dict[str, Any]) -> str:
    """Hash the evidence content and its source relationship, excluding its identifier."""
    return sha256_json(_provenance_payload(item))


def _evidence_item(**values: Any) -> MlEvidenceItem:
    identity = str(values.pop("identity"))
    evidence_id = stable_id("evidence", CONTRACT_VERSION, identity)
    draft = MlEvidenceItem.model_validate(
        {
            "evidence_id": evidence_id,
            **values,
            "provenance_hash": "sha256:" + "0" * 64,
        }
    )
    return draft.model_copy(update={"provenance_hash": evidence_provenance_hash(draft)})


def _metadata_source(sources: list[Source]) -> Source:
    if not sources:
        raise ValueError("canonical book has no provenance source")
    return min(
        sources,
        key=lambda source: (
            source.source_type != "metadata_api",
            source.provider,
            source.source_id,
        ),
    )


def _edition_relation(source: Source) -> EditionRelation:
    if source.evidence is None or source.evidence.same_edition is None:
        return "unspecified"
    return "exact" if source.evidence.same_edition else "same_work"


def _toc_evidence_type(source: Source) -> TocEvidenceType:
    evidence = source.evidence
    if evidence is not None and evidence.tier == "same_work_alternate_edition_toc":
        return "toc_same_work"
    if (
        source.source_type in {"publisher_page", "author_page"}
        or (evidence is not None and evidence.source_document_type == "public_html")
        or (evidence is not None and evidence.tier == "validated_public_web_toc")
    ):
        return "toc_public_web_exact"
    return "toc_exact"


def _toc_entries_in_order(entries: list[TocEntry]) -> list[tuple[TocEntry, list[str]]]:
    by_parent: dict[str | None, list[TocEntry]] = defaultdict(list)
    for entry in entries:
        by_parent[entry.parent_entry_id].append(entry)
    for children in by_parent.values():
        children.sort(
            key=lambda item: (
                item.order_index,
                item.label or "",
                item.title,
                item.toc_entry_id,
            )
        )

    ordered: list[tuple[TocEntry, list[str]]] = []

    def visit(entry: TocEntry, path: list[str]) -> None:
        current_path = [*path, entry.title]
        ordered.append((entry, current_path))
        for child in by_parent.get(entry.toc_entry_id, []):
            visit(child, current_path)

    for root in by_parent.get(None, []):
        visit(root, [])
    return ordered


def _source_fields(source: Source) -> dict[str, Any]:
    return {
        "source_id": source.source_id,
        "provider": source.provider,
        "source_type": source.source_type,
        "source_url": source.url,
        "source_retrieved_at": source.retrieved_at,
        "source_content_hash": source.content_hash,
        "source_evidence_tier": source.evidence.tier if source.evidence is not None else None,
        "source_evidence": source.evidence,
    }


def export_ml_evidence(dataset: CanonicalDataset) -> list[MlBookEvidence]:
    """Project canonical records into deterministic per-book ML evidence records."""
    sources_by_id = {source.source_id: source for source in dataset.sources}
    sources_by_book: dict[str, list[Source]] = defaultdict(list)
    documents_by_book: dict[str, list[Document]] = defaultdict(list)
    toc_by_book: dict[str, list[TocEntry]] = defaultdict(list)
    for source in dataset.sources:
        sources_by_book[source.book_id].append(source)
    for document in dataset.documents:
        documents_by_book[document.book_id].append(document)
    for entry in dataset.toc:
        toc_by_book[entry.book_id].append(entry)

    records = []
    for book in sorted(dataset.books, key=lambda item: item.book_id):
        metadata_source = _metadata_source(sources_by_book[book.book_id])
        evidence: list[MlEvidenceItem] = [
            _evidence_item(
                identity=f"{book.book_id}:metadata:title",
                evidence_type="metadata_minimal",
                text=" — ".join(value for value in (book.title, book.subtitle) if value),
                edition_relation="canonical_record",
                metadata_field="title",
                **_source_fields(metadata_source),
            )
        ]
        evidence.extend(
            _evidence_item(
                identity=f"{book.book_id}:metadata:topics:{topic}",
                evidence_type="subject",
                text=topic,
                edition_relation="canonical_record",
                metadata_field="topics",
                **_source_fields(metadata_source),
            )
            for topic in sorted(set(book.topics))
        )

        for document in sorted(
            documents_by_book.get(book.book_id, []), key=lambda item: item.document_id
        ):
            source = sources_by_id[document.source_id]
            evidence_type = (
                "description"
                if document.document_type in {"description", "publisher_summary"}
                else "document"
            )
            evidence.append(
                _evidence_item(
                    identity=f"{book.book_id}:document:{document.document_id}",
                    evidence_type=evidence_type,
                    text=document.text,
                    edition_relation=_edition_relation(source),
                    document_id=document.document_id,
                    document_type=document.document_type,
                    document_content_hash=document.content_hash,
                    **_source_fields(source),
                )
            )

        for entry, toc_path in _toc_entries_in_order(toc_by_book.get(book.book_id, [])):
            source = sources_by_id[entry.source_id]
            toc_type = _toc_evidence_type(source)
            evidence.append(
                _evidence_item(
                    identity=f"{book.book_id}:toc:{entry.toc_entry_id}:{toc_type}",
                    evidence_type=toc_type,
                    text=entry.title,
                    edition_relation="same_work" if toc_type == "toc_same_work" else "exact",
                    toc_entry_id=entry.toc_entry_id,
                    parent_entry_id=entry.parent_entry_id,
                    level=entry.level,
                    order_index=entry.order_index,
                    label=entry.label,
                    toc_path=toc_path,
                    **_source_fields(source),
                )
            )

        records.append(
            MlBookEvidence(
                book=book,
                book_content_hash=sha256_json(book.model_dump(mode="json")),
                evidence=evidence,
            )
        )
    return records


def validate_ml_evidence(records: list[MlBookEvidence], canonical: CanonicalDataset) -> list[str]:
    """Validate evidence identity, provenance, source ownership, and tier semantics."""
    errors: list[str] = []
    if not records:
        errors.append("ML evidence artifact has zero books")
    canonical_books = {book.book_id: book for book in canonical.books}
    sources = {source.source_id: source for source in canonical.sources}
    documents = {document.document_id: document for document in canonical.documents}
    toc_entries = {entry.toc_entry_id: entry for entry in canonical.toc}
    record_ids = [record.book.book_id for record in records]
    for book_id, count in Counter(record_ids).items():
        if count > 1:
            errors.append(f"duplicate ML evidence book: {book_id}")
    if set(record_ids) != set(canonical_books):
        errors.append("ML evidence book identities do not match canonical books")

    evidence_ids: list[str] = []
    for record in records:
        canonical_book = canonical_books.get(record.book.book_id)
        if canonical_book is not None and record.book != canonical_book:
            errors.append(f"ML evidence book metadata differs: {record.book.book_id}")
        if record.book_content_hash != sha256_json(record.book.model_dump(mode="json")):
            errors.append(f"ML evidence book hash mismatch: {record.book.book_id}")
        if not record.evidence:
            errors.append(f"ML evidence book has zero evidence: {record.book.book_id}")
        for item in record.evidence:
            evidence_ids.append(item.evidence_id)
            source = sources.get(item.source_id)
            if source is None:
                errors.append(f"ML evidence {item.evidence_id} references missing source")
            elif source.book_id != record.book.book_id:
                errors.append(
                    f"ML evidence {item.evidence_id} references source owned by {source.book_id}"
                )
            elif (
                item.provider != source.provider
                or item.source_type != source.source_type
                or item.source_url != source.url
                or item.source_retrieved_at != source.retrieved_at
                or item.source_content_hash != source.content_hash
                or item.source_evidence_tier
                != (source.evidence.tier if source.evidence is not None else None)
                or item.source_evidence != source.evidence
            ):
                errors.append(f"ML evidence source provenance differs: {item.evidence_id}")
            if evidence_provenance_hash(item) != item.provenance_hash:
                errors.append(f"ML evidence provenance hash mismatch: {item.evidence_id}")
            if item.evidence_type.startswith("toc_"):
                entry = toc_entries.get(item.toc_entry_id or "")
                if entry is None:
                    errors.append(f"ML evidence references missing TOC: {item.evidence_id}")
                elif (
                    entry.book_id != record.book.book_id
                    or entry.source_id != item.source_id
                    or entry.title != item.text
                    or entry.parent_entry_id != item.parent_entry_id
                    or entry.level != item.level
                    or entry.order_index != item.order_index
                    or entry.label != item.label
                ):
                    errors.append(f"ML evidence differs from canonical TOC: {item.evidence_id}")
            if item.evidence_type in {"description", "document"}:
                document = documents.get(item.document_id or "")
                if document is None:
                    errors.append(f"ML evidence references missing document: {item.evidence_id}")
                elif (
                    document.book_id != record.book.book_id
                    or document.source_id != item.source_id
                    or document.text != item.text
                    or document.document_type != item.document_type
                    or document.content_hash != item.document_content_hash
                ):
                    errors.append(
                        f"ML evidence differs from canonical document: {item.evidence_id}"
                    )
            if item.evidence_type == "toc_same_work":
                if item.edition_relation != "same_work":
                    errors.append(f"same-Work TOC is not marked same_work: {item.evidence_id}")
                if item.source_evidence_tier != "same_work_alternate_edition_toc":
                    errors.append(f"same-Work TOC lacks alternate provenance: {item.evidence_id}")
            if item.evidence_type in {"toc_exact", "toc_public_web_exact"} and (
                item.edition_relation != "exact"
            ):
                errors.append(f"exact TOC is not marked exact: {item.evidence_id}")
            if item.evidence_type in {"description", "document"} and item.toc_entry_id:
                errors.append(f"document mislabeled with TOC identity: {item.evidence_id}")
    for evidence_id, count in Counter(evidence_ids).items():
        if count > 1:
            errors.append(f"duplicate ML evidence ID: {evidence_id}")

    expected = {record.book.book_id: record for record in export_ml_evidence(canonical)}
    for record in records:
        expected_record = expected.get(record.book.book_id)
        if expected_record is not None and record != expected_record:
            errors.append(
                f"ML evidence differs from deterministic canonical projection: "
                f"{record.book.book_id}"
            )
    return errors


def summarize_ml_evidence(
    records: list[MlBookEvidence], validation_errors: list[str]
) -> dict[str, Any]:
    """Return coverage and provenance counts without inventing confidence scores."""
    evidence_type_rows = Counter(
        item.evidence_type for record in records for item in record.evidence
    )
    referenced_sources: dict[str, str] = {}
    toc_types = {"toc_exact", "toc_same_work", "toc_public_web_exact"}
    books_with_toc = 0
    books_with_exact = 0
    books_with_same_work = 0
    books_with_public_web = 0
    metadata_only = 0
    zero = 0
    for record in records:
        types = {item.evidence_type for item in record.evidence}
        has_toc = bool(types & toc_types)
        books_with_toc += has_toc
        books_with_exact += bool(types & {"toc_exact", "toc_public_web_exact"})
        books_with_same_work += "toc_same_work" in types
        books_with_public_web += "toc_public_web_exact" in types
        metadata_only += not has_toc
        zero += not record.evidence
        for item in record.evidence:
            referenced_sources[item.source_id] = item.provider
    return {
        "schema_version": 1,
        "contract_version": CONTRACT_VERSION,
        "total_books": len(records),
        "books_with_toc_evidence": books_with_toc,
        "books_with_exact_toc": books_with_exact,
        "books_with_same_work_alternate_toc": books_with_same_work,
        "books_with_public_web_toc": books_with_public_web,
        "metadata_fallback_only": metadata_only,
        "evidence_type_rows": dict(sorted(evidence_type_rows.items())),
        "provider_source_counts": dict(sorted(Counter(referenced_sources.values()).items())),
        "books_with_zero_evidence": zero,
        "validation_errors": validation_errors,
    }


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        mode="w",
        encoding="utf-8",
        delete=False,
    ) as stream:
        temporary = Path(stream.name)
        stream.write(content)
    try:
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def write_ml_evidence(records: list[MlBookEvidence], path: Path) -> None:
    """Atomically write deterministic one-book-per-line JSONL."""
    content = "".join(record.model_dump_json(exclude_none=False) + "\n" for record in records)
    _atomic_write(path, content)


def read_ml_evidence(path: Path) -> list[MlBookEvidence]:
    """Load a generated ML evidence JSONL artifact."""
    return [
        MlBookEvidence.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def write_ml_evidence_summary(summary: dict[str, Any], path: Path) -> None:
    """Atomically write a stable, human-readable summary report."""
    _atomic_write(
        path,
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
