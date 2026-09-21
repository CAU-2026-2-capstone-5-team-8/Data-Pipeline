import pytest

from data_pipeline.datasets import DatasetMergeError, merge_datasets
from data_pipeline.models import CanonicalDataset
from data_pipeline.public_book_sources import public_book_source, public_book_source_id
from tests.test_storage_validation import make_dataset


def test_merge_accumulates_distinct_topic_datasets() -> None:
    operating_systems = make_dataset()
    linear_algebra_book = operating_systems.books[0].model_copy(
        update={
            "book_id": "isbn13:9780471694663",
            "isbn_10": "0471694665",
            "isbn_13": "9780471694663",
            "title": "Linear Algebra",
            "topics": ["mathematics", "linear-algebra"],
        }
    )
    linear_algebra_source = operating_systems.sources[0].model_copy(
        update={
            "source_id": "source_linear_algebra",
            "book_id": linear_algebra_book.book_id,
        }
    )
    linear_algebra = CanonicalDataset(
        books=[linear_algebra_book],
        documents=[],
        toc=[],
        sources=[linear_algebra_source],
    )

    merged = merge_datasets([operating_systems, linear_algebra])

    assert len(merged.books) == 2
    assert {book.topics[-1] for book in merged.books} == {
        "operating-systems",
        "linear-algebra",
    }


def test_merge_rejects_conflicting_book_metadata() -> None:
    first = make_dataset()
    conflicting = first.model_copy(deep=True)
    conflicting.books[0].publisher = "Different Publisher"

    with pytest.raises(DatasetMergeError, match="conflicting book_id"):
        merge_datasets([first, conflicting])


def test_merge_selects_reviewed_preferred_toc_in_either_input_order() -> None:
    source_spec = public_book_source("ecampus-osc-essentials2")
    partial = make_dataset()
    book = partial.books[0].model_copy(
        update={
            "book_id": source_spec.book_id,
            "isbn_10": "1118804929",
            "isbn_13": source_spec.isbn_13,
            "title": source_spec.title,
        }
    )
    old_source = partial.sources[0].model_copy(
        update={"source_id": "partial-source", "book_id": source_spec.book_id}
    )
    old_entry = partial.toc[0].model_copy(
        update={
            "toc_entry_id": "partial-entry",
            "book_id": source_spec.book_id,
            "source_id": old_source.source_id,
        }
    )
    old = CanonicalDataset(books=[book], documents=[], toc=[old_entry], sources=[old_source])
    preferred_source = old_source.model_copy(
        update={
            "source_id": public_book_source_id(source_spec),
            "provider": source_spec.provider,
            "url": source_spec.url,
        }
    )
    preferred_entry = old_entry.model_copy(
        update={
            "toc_entry_id": "preferred-entry",
            "source_id": preferred_source.source_id,
        }
    )
    preferred = CanonicalDataset(
        books=[], documents=[], toc=[preferred_entry], sources=[preferred_source]
    )

    for datasets in ([old, preferred], [preferred, old]):
        merged = merge_datasets(datasets)
        assert [entry.toc_entry_id for entry in merged.toc] == ["preferred-entry"]
        assert {source.source_id for source in merged.sources} == {
            "partial-source",
            preferred_source.source_id,
        }
