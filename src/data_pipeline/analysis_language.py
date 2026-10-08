"""Prepare English analysis fields without calling a translation provider."""

import re

from data_pipeline.models import CanonicalDataset

NON_ENGLISH_SCRIPT = re.compile(
    r"[\u0400-\u052f\u0600-\u06ff\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]"
)


def original_english(text: str, language: str | None) -> str | None:
    """Copy English fields in the supported English/Korean collection scope."""
    if language in {"en", "ko"} and not NON_ENGLISH_SCRIPT.search(text):
        return text
    return None


def copy_english_fields(
    dataset: CanonicalDataset, languages: dict[str, str] | None = None
) -> CanonicalDataset:
    """Fill only missing English fields, preserving inputs and existing translations."""
    result = dataset.model_copy(deep=True)
    language_by_book = dict(languages or {})
    language_by_book.update({book.book_id: book.language for book in result.books})
    for book in result.books:
        if book.en_title is None:
            book.en_title = original_english(book.title, book.language)
        if book.subtitle and book.en_subtitle is None:
            book.en_subtitle = original_english(book.subtitle, book.language)
    for entry in result.toc:
        if entry.en_title is None:
            entry.en_title = original_english(entry.title, language_by_book.get(entry.book_id))
    for document in result.documents:
        if document.en_text is None:
            document.en_text = original_english(
                document.text, language_by_book.get(document.book_id)
            )
    return result
