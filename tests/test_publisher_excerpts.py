"""Synthetic publisher HTML; no third-party book text is embedded in these tests."""

import json
from datetime import UTC, datetime

import httpx
import pytest
from typer.testing import CliRunner

from data_pipeline.cli import app
from data_pipeline.identifiers import sha256_text
from data_pipeline.models import Book, CanonicalDataset, Source
from data_pipeline.publisher_excerpts import (
    MAX_HTML_BYTES,
    fetch_excerpt_page,
    normalize_preface_excerpt,
    validate_excerpt_url,
)
from data_pipeline.storage import RawArtifact, read_dataset, write_dataset, write_raw_response

URL = "https://www.kyungmoon.com/shop/item.php?device=pc&it_id=123456"
NOW = datetime(2026, 10, 3, tzinfo=UTC)
TEXT = "합성 검증 자료입니다. 실제 도서에서 가져온 문장이 아닙니다.\r\n" * 6
HTML = (
    '<h2 id="sit_title">검증용 선형대수학 요약정보 및 구매</h2>'
    '<table class="sit_ov_tbl"><tr><th>ISBN</th><td>9780306406157</td></tr></table>'
    '<div id="sit_introduce_explan"><p>' + TEXT + "-머리말 중에서-</p></div>"
    '<div id="recommendations">다른 책의 소개 및 ISBN 9781119800361</div>'
)
BOOK = Book(
    book_id="isbn13:9780306406157",
    isbn_13="9780306406157",
    title="검증용 선형대수학",
    authors=["테스트 저자"],
    language="ko",
    topics=["mathematics", "linear-algebra"],
)


def normalize(html=HTML, book=BOOK):
    return normalize_preface_excerpt({"url": URL, "html": html}, book, NOW)


def original_dataset():
    return CanonicalDataset(
        books=[BOOK],
        documents=[],
        toc=[],
        sources=[
            Source(
                source_id="original-metadata",
                book_id=BOOK.book_id,
                provider="synthetic",
                source_type="metadata_api",
                url="https://example.com/book",
                retrieved_at=NOW,
                content_hash=sha256_text("synthetic metadata"),
            )
        ],
    )


def test_preface_excerpt_has_exact_identity_original_text_and_partial_rights_note():
    result = normalize()
    doc, source = result.documents[0], result.sources[0]
    # HTML parsing normalizes line endings; the raw HTML/hash retain the exact response.
    assert doc.text == TEXT.replace("\r\n", "\n") + "-머리말 중에서-"
    assert doc.content_hash == sha256_text(doc.text)
    assert source.content_hash == sha256_text(HTML)
    assert doc.document_type == "preface" and result.toc == []
    assert source.external_id.endswith(":preface_excerpt")
    assert source.license is None and "Partial excerpt" in source.rights_note
    assert source.url == URL and source.retrieved_at == NOW
    assert result.books == [BOOK]
    assert normalize() == result


@pytest.mark.parametrize(
    "marker", ["-머리말 中에서-", "-\n머리말 \n中\n에서\n-", "머리말 중\n에서"]
)
def test_explicit_attribution_variants_preserve_original_text_and_extent(marker):
    result = normalize(HTML.replace("-머리말 중에서-", marker))
    doc, source = result.documents[0], result.sources[0]
    assert doc.text.endswith(marker)
    assert doc.text_extent.scope == "excerpt"
    assert ("中" in doc.text_extent.basis) == ("中" in marker)
    assert ("中" in source.rights_note) == ("中" in marker)
    assert doc.content_hash == sha256_text(doc.text)


@pytest.mark.parametrize(
    "marker", ["머리말 中", "머리말 中에서 가져올 예정", "中에서", "서문 중에서"]
)
def test_incomplete_or_nonterminal_attribution_is_not_promoted(marker):
    with pytest.raises(ValueError, match="explicitly attributed"):
        normalize(HTML.replace("-머리말 중에서-", marker))


@pytest.mark.parametrize(
    "html",
    [
        HTML.replace("-머리말 중에서-", "일반 도서소개"),
        HTML.replace(TEXT, "짧은 내용"),
        HTML.replace("9780306406157", "9781119800361"),
        HTML.replace("검증용 선형대수학", "관계없는 책"),
        HTML.replace('id="sit_introduce_explan"', 'id="other"'),
        HTML + '<div id="sit_introduce_explan">중복</div>',
        HTML.replace("-머리말 중에서-", "<span hidden>-머리말 중에서-</span>"),
    ],
)
def test_unverified_description_identity_or_hidden_attribution_is_rejected(html):
    with pytest.raises(ValueError):
        normalize(html)


def test_korean_excerpt_does_not_attach_to_english_original():
    with pytest.raises(ValueError, match="Korean"):
        normalize(book=BOOK.model_copy(update={"language": "en"}))


@pytest.mark.parametrize(
    "url",
    [
        "http://www.kyungmoon.com/shop/item.php?it_id=123",
        "https://www.kyungmoon.com.evil.test/shop/item.php?it_id=123",
        "https://user@www.kyungmoon.com/shop/item.php?it_id=123",
        "https://www.kyungmoon.com/shop/item.php?it_id=123&it_id=456",
        "https://www.kyungmoon.com/private?it_id=123",
        "https://www.kyungmoon.com/shop/item.php?it_id=123&download=1",
    ],
)
def test_only_public_product_routes_are_accepted(url):
    with pytest.raises(ValueError):
        validate_excerpt_url(url)


@pytest.mark.parametrize(
    "status,headers,body",
    [
        (403, {"content-type": "text/html"}, b"denied"),
        (302, {"location": "https://example.com"}, b""),
        (200, {"content-type": "application/pdf"}, b"%PDF-"),
        (200, {"content-type": "text/html"}, b"x" * (MAX_HTML_BYTES + 1)),
        (200, {"content-type": "text/html"}, b"\xff"),
    ],
)
def test_fetch_does_not_retry_restricted_or_unsupported_content(status, headers, body):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(status, headers=headers, content=body)

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
        pytest.raises((ValueError, httpx.HTTPError)),
    ):
        fetch_excerpt_page(URL, client=client)
    assert len(requests) == 1


def test_live_collection_then_offline_replays_preserve_canonical_inputs(tmp_path, monkeypatch):
    existing = original_dataset()
    root = tmp_path / "input"
    write_dataset(existing, root / "processed")
    before = {p.name: p.read_bytes() for p in (root / "processed").iterdir()}
    monkeypatch.setattr(
        "data_pipeline.cli.fetch_excerpt_page", lambda url: {"url": url, "html": HTML}
    )
    runner = CliRunner()
    base = [
        "enrich-publisher-excerpt",
        "--data-dir",
        str(root),
        "--isbn",
        BOOK.isbn_13,
        "--topic",
        "linear-algebra",
    ]
    live = tmp_path / "live"
    response = runner.invoke(app, [*base, "--output-dir", str(live), "--url", URL])
    assert response.exit_code == 0, response.output
    raw = next((live / "raw").rglob("*.json"))

    def no_network(*args, **kwargs):
        pytest.fail("offline replay made a network request")

    monkeypatch.setattr("data_pipeline.cli.fetch_excerpt_page", no_network)
    for name in ["replay1", "replay2"]:
        output = tmp_path / name
        response = runner.invoke(app, [*base, "--output-dir", str(output), "--raw", str(raw)])
        assert response.exit_code == 0, response.output
        for p in (live / "processed").iterdir():
            assert p.read_bytes() == (output / "processed" / p.name).read_bytes()
    assert {p.name: p.read_bytes() for p in (root / "processed").iterdir()} == before
    manifest = json.loads((live / "enrichment.json").read_text())
    assert manifest["coverage"] == "preface_excerpt_only" and not manifest["complete_preface"]
    assert read_dataset(live / "processed").books == existing.books
    assert runner.invoke(app, [*base, "--output-dir", str(live), "--raw", str(raw)]).exit_code != 0
    mismatch = tmp_path / "wrong.json"
    artifact = RawArtifact.model_validate_json(raw.read_text()).model_copy(
        update={"request_parameters": {"isbn": "9781119800361", "url": URL}}
    )
    write_raw_response(artifact, mismatch)
    response = runner.invoke(
        app, [*base, "--output-dir", str(tmp_path / "wrong"), "--raw", str(mismatch)]
    )
    assert response.exit_code != 0 and "request identity mismatch" in response.output
    assert not (tmp_path / "wrong").exists()


def test_invalid_live_identity_preserves_raw_without_publishing_canonical(tmp_path, monkeypatch):
    root = tmp_path / "input"
    write_dataset(original_dataset(), root / "processed")
    monkeypatch.setattr(
        "data_pipeline.cli.fetch_excerpt_page",
        lambda url: {"url": url, "html": HTML.replace("9780306406157", "9781119800361")},
    )
    output = tmp_path / "failed"
    response = CliRunner().invoke(
        app,
        [
            "enrich-publisher-excerpt",
            "--data-dir",
            str(root),
            "--output-dir",
            str(output),
            "--isbn",
            BOOK.isbn_13,
            "--topic",
            "linear-algebra",
            "--url",
            URL,
        ],
    )
    assert response.exit_code != 0 and "preserved" in response.output
    assert len(list((output / "raw").rglob("*.json"))) == 1
    assert not (output / "processed").exists()
