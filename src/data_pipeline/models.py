"""Provider-independent canonical dataset models."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from data_pipeline.identifiers import is_valid_isbn_10, is_valid_isbn_13

DocumentType = Literal[
    "description",
    "publisher_summary",
    "preface",
    "introduction",
    "preview",
    "sample_chapter",
    "index",
    "other",
]
SourceType = Literal[
    "metadata_api",
    "publisher_page",
    "author_page",
    "open_textbook",
    "preview_page",
    "sample_page",
    "other",
]
EvidenceTier = Literal[
    "exact_edition_toc",
    "same_work_alternate_edition_toc",
    "validated_public_structured_toc",
    "validated_public_web_toc",
    "metadata_fallback",
]


class CanonicalModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Book(CanonicalModel):
    book_id: str = Field(pattern=r"^(isbn13:[0-9]{13}|isbn10:[0-9]{9}[0-9X]|book_[0-9a-f]{20})$")
    isbn_10: str | None = None
    isbn_13: str | None = None
    title: str = Field(min_length=1)
    subtitle: str | None = None
    authors: list[str]
    publisher: str | None = None
    published_year: int | None = Field(default=None, ge=1000, le=9999)
    language: str = Field(pattern=r"^[a-z]{2,3}$")
    topics: list[str] = Field(min_length=1)

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("title must not be blank")
        return value

    @field_validator("isbn_10")
    @classmethod
    def isbn_10_must_be_valid(cls, value: str | None) -> str | None:
        if value is not None and not is_valid_isbn_10(value):
            raise ValueError("invalid ISBN-10 check digit")
        return value

    @field_validator("isbn_13")
    @classmethod
    def isbn_13_must_be_valid(cls, value: str | None) -> str | None:
        if value is not None and not is_valid_isbn_13(value):
            raise ValueError("invalid ISBN-13 check digit")
        return value

    @model_validator(mode="after")
    def isbn_book_id_must_match(self) -> "Book":
        if self.isbn_13 is not None and self.book_id != f"isbn13:{self.isbn_13}":
            raise ValueError("book_id must use the record's ISBN-13")
        if (
            self.isbn_13 is None
            and self.isbn_10 is not None
            and self.book_id != f"isbn10:{self.isbn_10}"
        ):
            raise ValueError("book_id must use the record's ISBN-10")
        return self


class Document(CanonicalModel):
    document_id: str = Field(min_length=1)
    book_id: str = Field(min_length=1)
    document_type: DocumentType
    text: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @field_validator("text")
    @classmethod
    def text_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("document text must not be blank")
        return value


class TocEntry(CanonicalModel):
    toc_entry_id: str = Field(min_length=1)
    book_id: str = Field(min_length=1)
    parent_entry_id: str | None = None
    level: int = Field(ge=1)
    order_index: int = Field(ge=0)
    label: str | None = None
    title: str = Field(min_length=1)
    source_id: str = Field(min_length=1)


class EvidenceProvenance(CanonicalModel):
    """Explain how evidence for a target book relates to its source edition."""

    evidence_type: Literal["toc", "metadata"]
    tier: EvidenceTier
    target_isbn: str | None = None
    target_title: str = Field(min_length=1)
    target_authors: list[str]
    source_edition_id: str | None = None
    source_isbns: list[str] = Field(default_factory=list)
    source_title: str | None = None
    source_author_ids: list[str] = Field(default_factory=list)
    same_edition: bool | None = None
    source_document_type: str | None = None
    discovery_method: str = Field(min_length=1)
    match_basis: list[str] = Field(min_length=1)
    validation_status: Literal["strong", "acceptable"]


class Source(CanonicalModel):
    source_id: str = Field(min_length=1)
    book_id: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    source_type: SourceType
    url: str = Field(min_length=1)
    external_id: str | None = None
    retrieved_at: datetime
    license: str | None = None
    rights_note: str | None = None
    content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    evidence: EvidenceProvenance | None = None

    @field_validator("retrieved_at")
    @classmethod
    def retrieved_at_must_include_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("retrieved_at must include a timezone")
        return value


class CanonicalDataset(CanonicalModel):
    books: list[Book]
    documents: list[Document]
    toc: list[TocEntry]
    sources: list[Source]
