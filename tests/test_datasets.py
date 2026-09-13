import pytest

from data_pipeline.datasets import DatasetMergeError, merge_datasets
from data_pipeline.models import CanonicalDataset
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
