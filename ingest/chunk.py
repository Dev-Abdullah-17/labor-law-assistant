"""Section-aware chunking of parsed acts into citable, metadata-tagged chunks.

Usage: python -m ingest.chunk

Reads data/interim/<doc_id>.json (produced by ingest.parse) and writes
data/processed/<doc_id>.json — a list of chunks, each carrying the full
metadata required by CLAUDE.md: {act_name, act_year, section_number,
section_title, page, source_url, version_date}.

Two real quirks in the source PDFs shape this design (see PROGRESS.md /
the Milestone 2 plan for how they were found):

1. In 4 of 5 documents, a section's marginal-note title is extracted
   *after* that section's body text, not before it — a column-layout
   artifact. Titles are therefore looked up from each document's own
   table of contents instead of parsed out of the (unreliably ordered)
   body text.
2. The Standing Orders Act renumbers from 1 inside a SCHEDULE block. Its
   items are kept in a separate numbering namespace ("Schedule Standing
   Order N") so they never collide with the main "Section N" numbering.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from ingest.sources import DocumentSource, core_sources

INTERIM_DIR = Path(__file__).resolve().parent.parent / "data" / "interim"
PROCESSED_DIR = Path(__file__).resolve().parent.parent / "data" / "processed"

ENACTED_MARKER_RE = re.compile(r"enacted as follows", re.IGNORECASE)
SCHEDULE_HEADING_RE = re.compile(r"^\s*SCHEDULE\s*$", re.MULTILINE)
# Section numbers are capped at 3 digits (no act here exceeds ~90 sections).
# This also protects against false positives from 4-digit years at the start
# of a wrapped line (e.g. "...Act, 2015.\n" or "...Ordinance, 1973.\n"), which
# a plain \d+ would otherwise mistake for a section boundary.
SECTION_START_RE = re.compile(r"^\s*(\d{1,3}[A-Z]?)\.\s+", re.MULTILINE)
TOC_ENTRY_RE = re.compile(r"^\s*(\d{1,3}[A-Z]?)\.\s+(.+)$")
TOC_TRAILING_LEADER_RE = re.compile(r"\.{2,}\s*\d+\s*$")
# A near-universal opener for a statute's recitals ("WHEREAS it is
# expedient...") and a standalone bracketed gazette/assent date (e.g.
# "[22nd March, 2017]") both mark the end of the TOC listing and the start
# of preamble prose — neither is ever a genuine TOC title continuation.
WHEREAS_RE = re.compile(r"^\s*WHEREAS\b", re.IGNORECASE)
BRACKETED_DATE_RE = re.compile(r"^\s*\[[^\]]*\d{4}\]\s*$")

MAX_SECTION_WORDS = 1200
OVERLAP_WORDS = 100
SUBCLAUSE_RE = re.compile(r"^\s*\(([a-z]|[ivx]+)\)\s+", re.MULTILINE)

MAIN_NAMESPACE = "Section"
SCHEDULE_NAMESPACE = "Schedule Standing Order"

UNKNOWN_TITLE = "UNKNOWN — not found in TOC"


@dataclass
class Section:
    namespace: str  # MAIN_NAMESPACE or SCHEDULE_NAMESPACE
    number: str
    text: str
    page: int


def _full_text_and_page_offsets(pages: list[dict]) -> tuple[str, list[tuple[int, int]]]:
    """Join page texts (unmodified, so line-anchored regexes stay safe) and
    record each page's starting character offset for later lookup."""
    parts: list[str] = []
    offsets: list[tuple[int, int]] = []
    pos = 0
    for p in pages:
        offsets.append((pos, p["page_number"]))
        parts.append(p["text"])
        pos += len(p["text"]) + 1  # +1 for the "\n" joiner below
    return "\n".join(parts), offsets


def _page_at_offset(offsets: list[tuple[int, int]], offset: int) -> int:
    """Return the page number of the last page whose start offset precedes `offset`."""
    page = offsets[0][1] if offsets else 1
    for start, number in offsets:
        if start > offset:
            break
        page = number
    return page


def _clean_toc_title(raw: str) -> str:
    title = TOC_TRAILING_LEADER_RE.sub("", raw).strip()
    return re.sub(r"\s+", " ", title)


REPEATED_LINE_MIN_OCCURRENCES = 10


def _repeated_lines(pages: list[dict]) -> set[str]:
    """Lines (page headers/footers) that repeat near-once-per-page across the
    whole document. Some scanned/compiled sources (e.g. a court-library
    reprint) stamp a running header on every page; that header can otherwise
    get swept into TOC title text as a spurious "continuation" line whenever
    an entry happens to wrap across a page break."""
    from collections import Counter

    counts: Counter[str] = Counter()
    for p in pages:
        for line in p["text"].splitlines():
            stripped = line.strip()
            if stripped:
                counts[stripped] += 1
    return {line for line, count in counts.items() if count >= REPEATED_LINE_MIN_OCCURRENCES}


def _looks_like_toc_end(line: str) -> bool:
    """A continuation-line candidate that signals we've left the TOC listing.

    Real TOC title-wrap continuations are lowercase prose fragments, though a
    long title's own trailing dot-leader + page number can wrap onto its own
    physical line (e.g. a bare "..................... 50"), which must still
    be absorbed rather than treated as an end-of-TOC signal. What genuinely
    signals TOC-end is a line carrying its *own* label text — either an
    unnumbered heading like "SCHEDULE .......... 57" (has real text before
    the dot-leader) or a fully upper-case document heading (e.g.
    "NOTIFICATION").
    """
    letters = [c for c in line if c.isalpha()]
    if len(letters) >= 3 and all(c.isupper() for c in letters):
        return True
    m = TOC_TRAILING_LEADER_RE.search(line)
    if m:
        before = line[: m.start()].strip()
        if any(c.isalpha() for c in before):
            return True
    if WHEREAS_RE.match(line) or BRACKETED_DATE_RE.match(line):
        return True
    return False


def _parse_toc_block(block: str, noise_lines: set[str] | None = None) -> dict[str, str]:
    """Parse a TOC region into {section_number: title}, joining wrapped lines."""
    noise_lines = noise_lines or set()
    entries: dict[str, str] = {}
    current_num: str | None = None
    current_lines: list[str] = []

    def flush() -> None:
        if current_num is not None:
            joined = " ".join(current_lines)
            entries[current_num] = _clean_toc_title(joined)

    for line in block.splitlines():
        stripped = line.strip()
        if not stripped or stripped in noise_lines:
            continue
        m = TOC_ENTRY_RE.match(line)
        if m:
            flush()
            current_num = m.group(1)
            current_lines = [m.group(2).strip()]
        elif current_num is not None:
            if _looks_like_toc_end(stripped):
                flush()
                current_num = None
                current_lines = []
                break
            current_lines.append(stripped)
    flush()
    return entries


def parse_toc(pages: list[dict]) -> tuple[dict[str, str], dict[str, str]]:
    """Extract (main_section_titles, schedule_titles) from the front-matter TOC."""
    full_text, _ = _full_text_and_page_offsets(pages)
    enact_match = ENACTED_MARKER_RE.search(full_text)
    front_matter = full_text[: enact_match.start()] if enact_match else full_text
    noise_lines = _repeated_lines(pages)

    schedule_match = SCHEDULE_HEADING_RE.search(front_matter)
    if schedule_match:
        main_block = front_matter[: schedule_match.start()]
        schedule_block = front_matter[schedule_match.end():]
    else:
        main_block = front_matter
        schedule_block = ""

    return _parse_toc_block(main_block, noise_lines), _parse_toc_block(schedule_block, noise_lines)


def _numeric_key(number: str) -> tuple[int, str]:
    m = re.match(r"(\d+)([A-Z]?)", number)
    return (int(m.group(1)), m.group(2)) if m else (0, "")


def _filter_out_of_sequence(starts: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Drop boundary candidates whose number doesn't strictly increase.

    Real section numbers always increase monotonically. A match like "14."
    appearing after section "22." in the body is not a real section restart
    — it's almost always the tail of a cross-reference sentence (e.g.
    "...recovered by an application under section \n14.") whose line-wrap
    happened to land the number at the start of a line. Such a match's
    "text" is really a trailing fragment of the previous genuine section and
    should stay folded into it rather than becoming a spurious new section.
    """
    filtered: list[tuple[int, str]] = []
    last_key: tuple[int, str] | None = None
    for start, number in starts:
        key = _numeric_key(number)
        if last_key is not None and key <= last_key:
            continue
        filtered.append((start, number))
        last_key = key
    return filtered


def find_section_boundaries(pages: list[dict]) -> list[Section]:
    """Split body text (after the enactment marker) into Section records."""
    full_text, offsets = _full_text_and_page_offsets(pages)
    enact_match = ENACTED_MARKER_RE.search(full_text)
    body_start = enact_match.end() if enact_match else 0
    body = full_text[body_start:]

    schedule_match = SCHEDULE_HEADING_RE.search(body)
    schedule_start = schedule_match.start() if schedule_match else None

    raw_starts = [(m.start(), m.group(1)) for m in SECTION_START_RE.finditer(body)]

    # The monotonicity filter must run separately per namespace, since the
    # Schedule namespace legitimately restarts numbering at 1.
    if schedule_start is None:
        starts = _filter_out_of_sequence(raw_starts)
    else:
        main_part = _filter_out_of_sequence([s for s in raw_starts if s[0] < schedule_start])
        schedule_part = _filter_out_of_sequence([s for s in raw_starts if s[0] >= schedule_start])
        starts = main_part + schedule_part

    sections: list[Section] = []
    for i, (start, number) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(body)
        text = body[start:end].strip()
        namespace = MAIN_NAMESPACE if schedule_start is None or start < schedule_start else SCHEDULE_NAMESPACE
        page = _page_at_offset(offsets, body_start + start)
        sections.append(Section(namespace=namespace, number=number, text=text, page=page))

    return sections


def _word_count(text: str) -> int:
    return len(text.split())


def split_oversized_section(text: str, max_words: int = MAX_SECTION_WORDS, overlap_words: int = OVERLAP_WORDS) -> list[str]:
    """Split an oversized section on sub-clause boundaries, never mid-sentence."""
    if _word_count(text) <= max_words:
        return [text]

    boundaries = [m.start() for m in SUBCLAUSE_RE.finditer(text)]
    if not boundaries:
        return _split_on_sentences(text, max_words, overlap_words)

    clauses = []
    for i, start in enumerate(boundaries):
        end = boundaries[i + 1] if i + 1 < len(boundaries) else len(text)
        clauses.append(text[start:end])
    if boundaries[0] > 0:
        clauses.insert(0, text[: boundaries[0]])

    return _pack_pieces_with_overlap(clauses, max_words, overlap_words)


def _split_on_sentences(text: str, max_words: int, overlap_words: int) -> list[str]:
    sentences = re.split(r"(?<=[.;])\s+", text)
    return _pack_pieces_with_overlap(sentences, max_words, overlap_words)


def _pack_pieces_with_overlap(pieces: list[str], max_words: int, overlap_words: int) -> list[str]:
    """Greedily pack whole pieces (sub-clauses or sentences) into <=max_words chunks,
    carrying the trailing overlap_words of the previous chunk into the next."""
    chunks: list[str] = []
    current: list[str] = []
    current_words = 0

    for piece in pieces:
        piece_words = _word_count(piece)
        if current and current_words + piece_words > max_words:
            chunk_text = "".join(current).strip()
            chunks.append(chunk_text)
            overlap_text = " ".join(chunk_text.split()[-overlap_words:])
            current = [overlap_text + " "] if overlap_text else []
            current_words = _word_count(overlap_text)
        current.append(piece)
        current_words += piece_words

    if current:
        chunks.append("".join(current).strip())

    return chunks


def _base_chunk_metadata(parsed: dict) -> dict:
    """Fields every chunk carries regardless of which chunking path produced it."""
    return {
        "act_name": parsed["act_name"],
        "act_year": parsed["act_year"],
        "source_url": parsed["source_url"],
        "version_date": parsed.get("version_date"),
        "ocr": parsed.get("ocr", False),
        "superseded_risk": parsed.get("superseded_risk", False),
    }


def _chunk_as_whole_document(parsed: dict) -> list[dict]:
    """Chunk a non-Act document (e.g. a gazette notification) as a whole.

    The section-boundary/TOC logic above assumes an Act's structure (an
    enactment clause, a table of contents, numbered sections with titles).
    A notification has none of that — just numbered conditions in a short
    announcement — so forcing it through that pipeline would misapply
    "Section N" labels to conditions that aren't sections of an Act at all.
    Simpler and honest: treat the whole document as one citable unit,
    split only if it's actually oversized.
    """
    pages = parsed["pages"]
    full_text, _ = _full_text_and_page_offsets(pages)
    pieces = split_oversized_section(full_text.strip())

    base = _base_chunk_metadata(parsed)
    first_page = pages[0]["page_number"] if pages else 1

    chunks: list[dict] = []
    for part_idx, piece_text in enumerate(pieces):
        chunk_id = f"{parsed['doc_id']}__whole_document"
        if len(pieces) > 1:
            chunk_id += f"__part{part_idx + 1}"
        chunks.append(
            {
                "chunk_id": chunk_id,
                "section_number": "Notification",
                "section_title": parsed["act_name"],
                "page": first_page,
                "text": piece_text,
                **base,
            }
        )
    return chunks


def chunk_document(parsed: dict) -> list[dict]:
    """Produce metadata-tagged chunks for one parsed document."""
    pages = parsed["pages"]
    full_text, _ = _full_text_and_page_offsets(pages)

    if ENACTED_MARKER_RE.search(full_text) is None:
        return _chunk_as_whole_document(parsed)

    main_titles, schedule_titles = parse_toc(pages)
    sections = find_section_boundaries(pages)

    base = _base_chunk_metadata(parsed)
    chunks: list[dict] = []
    for section in sections:
        titles = main_titles if section.namespace == MAIN_NAMESPACE else schedule_titles
        title = titles.get(section.number, UNKNOWN_TITLE)
        section_number_label = f"{section.namespace} {section.number}"

        pieces = split_oversized_section(section.text)
        for part_idx, piece_text in enumerate(pieces):
            chunk_id = f"{parsed['doc_id']}__{section.namespace.replace(' ', '_')}_{section.number}"
            if len(pieces) > 1:
                chunk_id += f"__part{part_idx + 1}"
            chunks.append(
                {
                    "chunk_id": chunk_id,
                    "section_number": section_number_label,
                    "section_title": title,
                    "page": section.page,
                    "text": piece_text,
                    **base,
                }
            )

    return chunks


def chunk_all(sources: list[DocumentSource] | None = None) -> tuple[list[str], list[str]]:
    """Chunk every core source with an available interim file.

    Returns (processed_doc_ids, missing_doc_ids).
    """
    sources = sources if sources is not None else core_sources()
    processed: list[str] = []
    missing: list[str] = []

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    for source in sources:
        interim_path = INTERIM_DIR / f"{source.doc_id}.json"
        if not interim_path.exists():
            missing.append(source.doc_id)
            continue

        parsed = json.loads(interim_path.read_text(encoding="utf-8"))
        parsed["doc_id"] = source.doc_id
        parsed["source_url"] = source.url
        parsed["version_date"] = source.version_date
        parsed["ocr"] = source.ocr
        parsed["superseded_risk"] = source.superseded_risk

        chunks = chunk_document(parsed)
        out_path = PROCESSED_DIR / f"{source.doc_id}.json"
        out_path.write_text(json.dumps(chunks, indent=2), encoding="utf-8")
        processed.append(source.doc_id)

    return processed, missing


def main() -> int:
    processed, missing = chunk_all()

    print(f"{'doc_id':<38} chunks")
    print("-" * 50)
    for doc_id in processed:
        chunks = json.loads((PROCESSED_DIR / f"{doc_id}.json").read_text(encoding="utf-8"))
        unknown_titles = sum(1 for c in chunks if c["section_title"] == UNKNOWN_TITLE)
        flag = f"  (!) {unknown_titles} chunk(s) with UNKNOWN title" if unknown_titles else ""
        print(f"{doc_id:<38} {len(chunks)}{flag}")

    if missing:
        print()
        for doc_id in missing:
            print(f"SKIPPED: {doc_id} — no data/interim/{doc_id}.json (run ingest.download + ingest.parse first, or source is unresolved).")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
