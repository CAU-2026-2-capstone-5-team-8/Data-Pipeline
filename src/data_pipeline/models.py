"""Provider-independent canonical dataset models."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

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


class CanonicalModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Book(CanonicalModel):
    book_id: str = Field(min_length=1)
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


class CanonicalDataset(CanonicalModel):
    books: list[Book]
    documents: list[Document]
    toc: list[TocEntry]
    sources: list[Source]
