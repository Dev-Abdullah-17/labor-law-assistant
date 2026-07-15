"""Milestone 4 evaluation pipeline.

Runs every question in eval/testset.jsonl through the real pipeline
(api.rewrite.rewrite_query -> retrieval.query.query -> api.generate.generate_answer)
and scores each of the three question types with the method appropriate to it:

- answerable: four RAGAS-style metrics (faithfulness, answer_relevancy,
  context_precision, context_recall), each scored 0.0-1.0 by an LLM judge.
- expected_refusal: binary correct/incorrect, evaluated against each
  question's own `expected_behavior` definition (see eval/testset.jsonl).
- follow_up: each turn is scored by its own `expected_outcome`'s method
  (answerable or expected_refusal, as above), plus a check that the
  rewritten standalone query (produced by api.rewrite.rewrite_query using
  the prior turn as history) actually names the right subject.

Note on the judge: SPEC.md/CLAUDE.md name RAGAS for this milestone. The
`ragas` package (0.4.3, the only version on PyPI) could not be made to
import in this environment — installing it silently corrupted the
project's numpy install (no prebuilt numpy wheel exists for Python 3.13,
so pip fell back to a from-source MinGW build that segfaulted on
`import numpy`), and separately has a hard, unconditional import of an
unused Google Vertex AI integration that no longer exists in current
langchain-community. Both were confirmed, not assumed (see PROGRESS.md).
Per explicit user decision, this module implements the same four metrics
directly as single-call LLM-judge prompts against the project's existing
Groq client, rather than fighting the dependency chain further.

Usage: python -m eval.run
"""

from __future__ import annotations

import json
import re
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from groq import APIConnectionError, Groq, RateLimitError

from api.generate import generate_answer
from api.rewrite import rewrite_query
from retrieval.query import query as retrieve

# This environment has documented, transient DNS/connection flakiness on
# longer-running network calls (see PROGRESS.md — hit previously with the
# Playwright and embedding-model downloads). A full eval run makes ~100
# sequential Groq calls, so a bare retry with backoff is needed for the run
# to complete reliably; it is not a general production reliability feature.
_MAX_RETRIES = 4
_RETRY_BACKOFF_SECONDS = 3
_RATE_LIMIT_WAIT_RE = re.compile(r"try again in (?:(\d+)m)?(\d+(?:\.\d+)?)s", re.IGNORECASE)


def _rate_limit_wait_seconds(exc: RateLimitError, default: float = 60.0) -> float:
    message = str(exc)
    match = _RATE_LIMIT_WAIT_RE.search(message)
    if not match:
        return default
    minutes = int(match.group(1)) if match.group(1) else 0
    seconds = float(match.group(2))
    return minutes * 60 + seconds + 2  # small safety margin


def _with_retry(fn, *args, **kwargs):
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            return fn(*args, **kwargs)
        except APIConnectionError:
            if attempt == _MAX_RETRIES:
                raise
            time.sleep(_RETRY_BACKOFF_SECONDS * attempt)
        except RateLimitError as exc:
            if attempt == _MAX_RETRIES:
                raise
            wait = _rate_limit_wait_seconds(exc)
            print(f"  [rate limited, waiting {wait:.0f}s before retry {attempt}/{_MAX_RETRIES}]", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError("unreachable: retry loop exhausted without returning or raising")

TESTSET_PATH = Path(__file__).resolve().parent / "testset.jsonl"
RESULTS_DIR = Path(__file__).resolve().parent / "results"

JUDGE_MODEL = "llama-3.1-8b-instant"

JUDGE_SYSTEM_PROMPT = """You are an evaluation judge for a legal RAG system covering Sindh, Pakistan labor law. \
Given a question, a human-written reference answer, the system's generated answer, and the retrieved \
source excerpts (contexts) the system had available, score the generated answer on four dimensions, \
each a float from 0.0 to 1.0:

- faithfulness: is every factual claim in the generated answer actually supported by the retrieved \
contexts? (1.0 = fully grounded in the contexts, 0.0 = fabricated or unsupported by them)
- answer_relevancy: does the generated answer directly and completely address the question asked? \
(1.0 = fully relevant and responsive, 0.0 = off-topic or non-responsive)
- context_precision: what proportion of the retrieved contexts are actually relevant to answering \
this specific question? (1.0 = all retrieved contexts are relevant, 0.0 = none are)
- context_recall: do the retrieved contexts, taken together, contain enough information to produce \
the reference answer? (1.0 = fully sufficient, 0.0 = missing key information the reference answer relies on)

Respond with ONLY a JSON object, no other text:
{"faithfulness": <float>, "answer_relevancy": <float>, "context_precision": <float>, "context_recall": <float>, "notes": "<one sentence>"}"""

_client: Groq | None = None


def _get_client() -> Groq:
    global _client
    if _client is None:
        _client = Groq()
    return _client


def _format_contexts(hits: list[dict]) -> str:
    parts = []
    for i, hit in enumerate(hits, 1):
        meta = hit["metadata"]
        parts.append(f"[{i}] {meta['act_name']} ({meta['act_year']}), {meta['section_number']}\n{hit['text']}")
    return "\n\n".join(parts) if parts else "(no contexts retrieved)"


def judge_answerable(question: str, reference_answer: str, generated_answer: str, hits: list[dict]) -> dict:
    """Score one answerable case on the four RAGAS-style dimensions via LLM judge."""
    user_content = (
        f"Question: {question}\n\n"
        f"Reference answer (ground truth): {reference_answer}\n\n"
        f"System's generated answer: {generated_answer}\n\n"
        f"Retrieved contexts:\n{_format_contexts(hits)}"
    )
    completion = _with_retry(
        _get_client().chat.completions.create,
        model=JUDGE_MODEL,
        messages=[
            {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        temperature=0,
    )
    raw = (completion.choices[0].message.content or "").strip()
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return {"faithfulness": None, "answer_relevancy": None, "context_precision": None, "context_recall": None, "notes": f"UNPARSEABLE JUDGE OUTPUT: {raw[:200]}"}
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {"faithfulness": None, "answer_relevancy": None, "context_precision": None, "context_recall": None, "notes": f"JSON PARSE ERROR: {raw[:200]}"}
    return {
        "faithfulness": parsed.get("faithfulness"),
        "answer_relevancy": parsed.get("answer_relevancy"),
        "context_precision": parsed.get("context_precision"),
        "context_recall": parsed.get("context_recall"),
        "notes": parsed.get("notes", ""),
    }


def score_refusal(answer: str, refused: bool, expected_behavior: dict) -> dict:
    """Binary correct/incorrect for an expected_refusal case, per its own expected_behavior rule."""
    strict = expected_behavior.get("strict_refusal_required", True)
    if strict:
        correct = refused is True
        reason = "refused as required" if correct else "did not refuse (strict refusal required)"
    else:
        fail_regex = expected_behavior.get("fail_regex", "")
        forbidden_found = bool(re.search(fail_regex, answer, re.IGNORECASE)) if fail_regex else False
        correct = not forbidden_found
        reason = "no forbidden pattern found" if correct else f"forbidden pattern matched: /{fail_regex}/"
    return {"correct": correct, "reason": reason}


def check_subject_naming(rewritten_query: str, subject_keywords: list[str]) -> dict:
    if not subject_keywords:
        return {"checked": False, "correct": None}
    lowered = rewritten_query.lower()
    matched = [kw for kw in subject_keywords if kw.lower() in lowered]
    return {"checked": True, "correct": bool(matched), "matched_keywords": matched, "rewritten_query": rewritten_query}


def load_testset() -> list[dict]:
    entries = []
    with open(TESTSET_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def run_single_turn(question: str, history: list[dict]) -> tuple[str, list[dict], dict]:
    """Run one turn through the real pipeline. Returns (standalone_query, hits, result)."""
    standalone_query = _with_retry(rewrite_query, question, history)
    hits = retrieve(standalone_query)
    result = _with_retry(generate_answer, standalone_query, hits)
    return standalone_query, hits, result


CHECKPOINT_PATH = RESULTS_DIR / "_checkpoint.json"


def load_checkpoint() -> dict:
    if CHECKPOINT_PATH.exists():
        return json.loads(CHECKPOINT_PATH.read_text(encoding="utf-8"))
    return {"answerable": {}, "refusal": {}, "follow_up_subject": {}}


def save_checkpoint(checkpoint: dict) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    CHECKPOINT_PATH.write_text(json.dumps(checkpoint, indent=2), encoding="utf-8")


def evaluate(entry_ids: set[str] | None = None) -> dict:
    """Run the eval pipeline, checkpointing after every case so a crash or a
    deliberately-batched run never repeats work already paid for in tokens.

    If `entry_ids` is given, only those top-level testset entry ids are
    processed this call (still skipping any already-checkpointed cases
    within them) — this is what makes running in small batches practical.
    """
    entries = load_testset()
    if entry_ids is not None:
        entries = [e for e in entries if e["id"] in entry_ids]
    checkpoint = load_checkpoint()

    for entry in entries:
        eid = entry["id"]
        etype = entry["type"]

        if etype in ("answerable", "expected_refusal"):
            bucket = "answerable" if etype == "answerable" else "refusal"
            if eid in checkpoint[bucket]:
                continue
            question = entry["question"]
            standalone_query, hits, result = run_single_turn(question, [])

            if etype == "answerable":
                judge = judge_answerable(question, entry["reference_answer"], result["answer"], hits)
                checkpoint["answerable"][eid] = {
                    "id": eid, "question": question, "known_hard": entry.get("known_hard", False),
                    "refused": result["refused"], "answer": result["answer"], **judge,
                }
            else:
                verdict = score_refusal(result["answer"], result["refused"], entry["expected_behavior"])
                checkpoint["refusal"][eid] = {
                    "id": eid, "question": question, "refused": result["refused"],
                    "answer": result["answer"], **verdict,
                }
            save_checkpoint(checkpoint)

        elif etype == "follow_up":
            history: list[dict] = []
            for turn_idx, turn in enumerate(entry["turns"]):
                turn_id = f"{eid}-turn{turn_idx + 1}"
                question = turn["question"]
                bucket = "answerable" if turn["expected_outcome"] == "answerable" else "refusal"

                if turn_id in checkpoint[bucket]:
                    # Already scored on a prior batch — reuse its stored answer to
                    # keep rebuilding history correctly for any later turn.
                    stored = checkpoint[bucket][turn_id]
                    history.append({"role": "user", "content": question})
                    history.append({"role": "assistant", "content": stored["answer"]})
                    continue

                standalone_query, hits, result = run_single_turn(question, history)

                subject_check = check_subject_naming(standalone_query, turn.get("subject_keywords", []))
                if subject_check["checked"] and turn_id not in checkpoint["follow_up_subject"]:
                    checkpoint["follow_up_subject"][turn_id] = {
                        "id": turn_id, "original_question": question, **subject_check,
                    }

                if turn["expected_outcome"] == "answerable":
                    judge = judge_answerable(question, turn["reference_answer"], result["answer"], hits)
                    checkpoint["answerable"][turn_id] = {
                        "id": turn_id, "question": question, "known_hard": False,
                        "refused": result["refused"], "answer": result["answer"], **judge,
                    }
                else:
                    verdict = score_refusal(result["answer"], result["refused"], turn["expected_behavior"])
                    checkpoint["refusal"][turn_id] = {
                        "id": turn_id, "question": question, "refused": result["refused"],
                        "answer": result["answer"], **verdict,
                    }
                save_checkpoint(checkpoint)

                history.append({"role": "user", "content": question})
                history.append({"role": "assistant", "content": result["answer"]})

    return {
        "answerable_results": list(checkpoint["answerable"].values()),
        "refusal_results": list(checkpoint["refusal"].values()),
        "follow_up_subject_results": list(checkpoint["follow_up_subject"].values()),
    }


def _mean(values: list[float | None]) -> float | None:
    clean = [v for v in values if v is not None]
    return sum(clean) / len(clean) if clean else None


def summarize(raw: dict) -> dict:
    answerable = raw["answerable_results"]
    refusal = raw["refusal_results"]
    follow_up = raw["follow_up_subject_results"]

    metric_names = ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]
    answerable_summary = {m: _mean([r[m] for r in answerable]) for m in metric_names}
    answerable_summary["n"] = len(answerable)
    answerable_summary["known_hard_ids"] = [r["id"] for r in answerable if r["known_hard"]]

    refusal_correct = [r for r in refusal if r["correct"]]
    refusal_summary = {
        "accuracy": len(refusal_correct) / len(refusal) if refusal else None,
        "n": len(refusal),
        "n_correct": len(refusal_correct),
        "failed_ids": [r["id"] for r in refusal if not r["correct"]],
    }

    follow_up_correct = [r for r in follow_up if r["correct"]]
    follow_up_summary = {
        "subject_naming_accuracy": len(follow_up_correct) / len(follow_up) if follow_up else None,
        "n": len(follow_up),
        "n_correct": len(follow_up_correct),
        "failed_ids": [r["id"] for r in follow_up if not r["correct"]],
    }

    return {
        "answerable": answerable_summary,
        "expected_refusal": refusal_summary,
        "follow_up_subject_naming": follow_up_summary,
    }


def print_summary_table(summary: dict) -> None:
    a = summary["answerable"]
    r = summary["expected_refusal"]
    f = summary["follow_up_subject_naming"]

    print()
    print("=" * 72)
    print("MILESTONE 4 BASELINE — SUMMARY")
    print("=" * 72)
    print(f"{'Category':<28}{'Metric':<24}{'Score':>10}   n")
    print("-" * 72)
    print(f"{'Answerable (' + str(a['n']) + ')':<28}{'faithfulness':<24}{_fmt(a['faithfulness']):>10}")
    print(f"{'':<28}{'answer_relevancy':<24}{_fmt(a['answer_relevancy']):>10}")
    print(f"{'':<28}{'context_precision':<24}{_fmt(a['context_precision']):>10}")
    print(f"{'':<28}{'context_recall':<24}{_fmt(a['context_recall']):>10}")
    print(f"{'Expected refusal':<28}{'binary accuracy':<24}{_fmt(r['accuracy']):>10}   {r['n_correct']}/{r['n']}")
    print(f"{'Follow-up rewriting':<28}{'subject-naming acc.':<24}{_fmt(f['subject_naming_accuracy']):>10}   {f['n_correct']}/{f['n']}")
    print("-" * 72)
    if a["known_hard_ids"]:
        print(f"known_hard (tracked, not counted against baseline): {a['known_hard_ids']}")
    if r["failed_ids"]:
        print(f"Failed refusal cases: {r['failed_ids']}")
    if f["failed_ids"]:
        print(f"Failed subject-naming cases: {f['failed_ids']}")
    print("=" * 72)


def _fmt(v: float | None) -> str:
    return f"{v:.3f}" if v is not None else "n/a"


def main() -> int:
    print(f"Loaded testset: {TESTSET_PATH}")

    entry_ids = None
    if len(sys.argv) > 1:
        entry_ids = {x.strip() for x in sys.argv[1].split(",") if x.strip()}
        print(f"Running batch: {sorted(entry_ids)}")

    raw = evaluate(entry_ids)
    summary = summarize(raw)
    print_summary_table(summary)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / f"{date.today().isoformat()}.json"
    payload = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "judge_model": JUDGE_MODEL,
        "summary": summary,
        "detail": raw,
    }
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nFull results saved to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
