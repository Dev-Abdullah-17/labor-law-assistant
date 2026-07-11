"""Download core source documents into data/raw/.

Usage: python -m ingest.download [--force]

For every core document in the registry, attempts exactly one URL — the one
recorded in ingest.sources. Never invents or falls back to an alternate URL.
Each attempt is classified as SUCCESS, FAILED, or SKIPPED_NO_URL and recorded
in data/raw/download_manifest.json. Exits non-zero if any core document is
not SUCCESS, printing an explicit ACTION REQUIRED line for each problem so a
human knows exactly what needs attention.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import requests

from ingest.sources import DocumentSource, core_sources

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
MANIFEST_PATH = RAW_DIR / "download_manifest.json"
REQUEST_TIMEOUT_SECONDS = 30
USER_AGENT = (
    "Mozilla/5.0 (compatible; LaborLawAssistantBot/1.0; "
    "+https://github.com/) research/portfolio project ingestion"
)

# Transient errors are worth one retry; a bad status code or content-type is
# terminal — retrying a wrong or blocked URL will not fix it.
TRANSIENT_EXCEPTIONS = (requests.exceptions.Timeout, requests.exceptions.ConnectionError)


@dataclass
class DownloadResult:
    doc_id: str
    act_name: str
    url: str | None
    status: str  # "SUCCESS" | "FAILED" | "SKIPPED_NO_URL"
    http_status: int | None
    error: str | None
    output_path: str | None
    sha256: str | None
    downloaded_at: str | None


def _sha256_of_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_manifest() -> dict[str, dict]:
    if not MANIFEST_PATH.exists():
        return {}
    entries = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return {entry["doc_id"]: entry for entry in entries}


def _attempt_download(source: DocumentSource, dest: Path) -> DownloadResult:
    """Attempt exactly one GET against source.url. No fallback URLs."""
    if source.url is None:
        return DownloadResult(
            doc_id=source.doc_id,
            act_name=source.act_name,
            url=None,
            status="SKIPPED_NO_URL",
            http_status=None,
            error="No URL is registered for this document in ingest.sources.",
            output_path=None,
            sha256=None,
            downloaded_at=None,
        )

    last_error: Exception | None = None
    for attempt in range(2):  # one retry, transient errors only
        try:
            response = requests.get(
                source.url,
                timeout=REQUEST_TIMEOUT_SECONDS,
                headers={"User-Agent": USER_AGENT},
            )
        except TRANSIENT_EXCEPTIONS as exc:
            last_error = exc
            continue

        content_type = response.headers.get("content-type", "")
        if response.status_code == 200 and "pdf" in content_type.lower():
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(response.content)
            return DownloadResult(
                doc_id=source.doc_id,
                act_name=source.act_name,
                url=source.url,
                status="SUCCESS",
                http_status=response.status_code,
                error=None,
                output_path=str(dest),
                sha256=_sha256_of_file(dest),
                downloaded_at=datetime.now(timezone.utc).isoformat(),
            )

        # Non-200 or wrong content-type is terminal — do not retry, do not
        # try any other URL.
        return DownloadResult(
            doc_id=source.doc_id,
            act_name=source.act_name,
            url=source.url,
            status="FAILED",
            http_status=response.status_code,
            error=f"Unexpected response: status={response.status_code}, content-type={content_type!r}",
            output_path=None,
            sha256=None,
            downloaded_at=None,
        )

    return DownloadResult(
        doc_id=source.doc_id,
        act_name=source.act_name,
        url=source.url,
        status="FAILED",
        http_status=None,
        error=f"Transient network error after retry: {last_error}",
        output_path=None,
        sha256=None,
        downloaded_at=None,
    )


def download_all(force: bool = False) -> list[DownloadResult]:
    """Download every core source, skipping unchanged files unless force=True."""
    existing_manifest = _load_manifest()
    results: list[DownloadResult] = []

    for source in core_sources():
        dest = RAW_DIR / source.output_filename
        previous = existing_manifest.get(source.doc_id)

        if (
            not force
            and previous is not None
            and previous.get("status") == "SUCCESS"
            and dest.exists()
            and _sha256_of_file(dest) == previous.get("sha256")
        ):
            results.append(DownloadResult(**previous))
            continue

        results.append(_attempt_download(source, dest))

    return results


def _write_manifest(results: list[DownloadResult]) -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(
        json.dumps([asdict(r) for r in results], indent=2),
        encoding="utf-8",
    )


def _print_report(results: list[DownloadResult]) -> None:
    print(f"{'doc_id':<38} {'status':<16} {'http':<6} detail")
    print("-" * 100)
    for r in results:
        detail = r.error or r.output_path or ""
        http = str(r.http_status) if r.http_status else "-"
        print(f"{r.doc_id:<38} {r.status:<16} {http:<6} {detail}")

    problems = [r for r in results if r.status != "SUCCESS"]
    if problems:
        print()
        for r in problems:
            print(f"ACTION REQUIRED: {r.doc_id} — {r.error}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force", action="store_true", help="Re-download even if a matching file already exists."
    )
    args = parser.parse_args()

    results = download_all(force=args.force)
    _write_manifest(results)
    _print_report(results)

    return 0 if all(r.status == "SUCCESS" for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
