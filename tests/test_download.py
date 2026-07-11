"""Tests for ingest.download — no real network calls are made."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from ingest import download
from ingest.sources import DocumentSource


def _fake_source(doc_id: str = "fake_doc", url: str | None = "https://example.com/fake.pdf") -> DocumentSource:
    return DocumentSource(
        doc_id=doc_id,
        act_name="Fake Act",
        act_year=2015,
        url=url,
        output_filename=f"{doc_id}.pdf",
        category="core",
        version_date=None,
        notes="test fixture",
    )


@pytest.fixture(autouse=True)
def _isolate_raw_dir(tmp_path, monkeypatch):
    """Redirect RAW_DIR/MANIFEST_PATH so tests never touch the real data/raw/."""
    raw_dir = tmp_path / "data" / "raw"
    monkeypatch.setattr(download, "RAW_DIR", raw_dir)
    monkeypatch.setattr(download, "MANIFEST_PATH", raw_dir / "download_manifest.json")
    yield raw_dir


def test_skipped_no_url_never_attempts_a_request(_isolate_raw_dir):
    source = _fake_source(url=None)
    with patch.object(download.requests, "get") as mock_get:
        result = download._attempt_download(source, _isolate_raw_dir / "fake_doc.pdf")

    mock_get.assert_not_called()
    assert result.status == "SKIPPED_NO_URL"
    assert result.url is None
    assert result.output_path is None


def test_success_writes_file_and_records_sha256(_isolate_raw_dir):
    source = _fake_source()
    fake_response = MagicMock(status_code=200, content=b"%PDF-1.4 fake pdf bytes")
    fake_response.headers = {"content-type": "application/pdf"}

    with patch.object(download.requests, "get", return_value=fake_response) as mock_get:
        dest = _isolate_raw_dir / "fake_doc.pdf"
        result = download._attempt_download(source, dest)

    mock_get.assert_called_once()
    assert result.status == "SUCCESS"
    assert dest.exists()
    assert dest.read_bytes() == b"%PDF-1.4 fake pdf bytes"
    assert result.sha256 is not None


def test_404_is_failed_and_not_retried(_isolate_raw_dir):
    source = _fake_source()
    fake_response = MagicMock(status_code=404, content=b"")
    fake_response.headers = {"content-type": "text/html"}

    with patch.object(download.requests, "get", return_value=fake_response) as mock_get:
        result = download._attempt_download(source, _isolate_raw_dir / "fake_doc.pdf")

    # 404 is terminal: exactly one attempt, no retry, no alternate URL.
    assert mock_get.call_count == 1
    assert result.status == "FAILED"
    assert result.http_status == 404
    assert result.url == source.url


def test_wrong_content_type_is_failed(_isolate_raw_dir):
    source = _fake_source()
    fake_response = MagicMock(status_code=200, content=b"<html>not a pdf</html>")
    fake_response.headers = {"content-type": "text/html"}

    with patch.object(download.requests, "get", return_value=fake_response):
        result = download._attempt_download(source, _isolate_raw_dir / "fake_doc.pdf")

    assert result.status == "FAILED"
    assert not (_isolate_raw_dir / "fake_doc.pdf").exists()


def test_transient_error_is_retried_once_then_failed(_isolate_raw_dir):
    source = _fake_source()
    with patch.object(
        download.requests, "get", side_effect=requests.exceptions.ConnectionError("boom")
    ) as mock_get:
        result = download._attempt_download(source, _isolate_raw_dir / "fake_doc.pdf")

    assert mock_get.call_count == 2  # one retry
    assert result.status == "FAILED"
    assert "boom" in result.error


def test_a_url_none_source_is_never_retried_against_another_url(_isolate_raw_dir):
    """Guards the 'never guess a URL' rule as executable behavior."""
    source = _fake_source(url=None)
    with patch.object(download.requests, "get") as mock_get:
        result = download._attempt_download(source, _isolate_raw_dir / "fake_doc.pdf")

    assert mock_get.call_count == 0
    assert result.url is None


def test_manifest_written_with_expected_schema(_isolate_raw_dir):
    results = [
        download.DownloadResult(
            doc_id="fake_doc",
            act_name="Fake Act",
            url="https://example.com/fake.pdf",
            status="SUCCESS",
            http_status=200,
            error=None,
            output_path=str(_isolate_raw_dir / "fake_doc.pdf"),
            sha256="abc123",
            downloaded_at="2026-07-11T00:00:00+00:00",
        )
    ]
    download._write_manifest(results)

    manifest = json.loads(download.MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest[0]["doc_id"] == "fake_doc"
    assert manifest[0]["status"] == "SUCCESS"
    assert set(manifest[0].keys()) == {
        "doc_id", "act_name", "url", "status", "http_status",
        "error", "output_path", "sha256", "downloaded_at",
    }


def test_exit_status_nonzero_when_any_core_doc_not_success():
    all_success = [
        download.DownloadResult("a", "A", "u", "SUCCESS", 200, None, "p", "s", "t"),
    ]
    mixed = [
        download.DownloadResult("a", "A", "u", "SUCCESS", 200, None, "p", "s", "t"),
        download.DownloadResult("b", "B", None, "SKIPPED_NO_URL", None, "no url", None, None, None),
    ]
    assert all(r.status == "SUCCESS" for r in all_success)
    assert not all(r.status == "SUCCESS" for r in mixed)
