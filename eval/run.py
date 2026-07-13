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
from datetime import date, datetime, timezone
from pathlib import Path

from groq import Groq

from api.generate import generate_answer
from api.rewrite import rewrite_query
from retrieval.query import query as retrieve

TESTSET_PATH = Path(__file__).resolve().parent / "testset.jsonl"
RESULTS_DIR = Path(__file__).resolve().parent / "results"

JUDGE_MODEL = "openai/gpt-oss-120b"

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
    completion = _get_client().chat.completions.create(
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
    standalone_query = rewrite_query(question, history)
    hits = retrieve(standalone_query)
    result = generate_answer(standalone_query, hits)
    return standalone_query, hits, result


def evaluate() -> dict:
    entries = load_testset()
    answerable_results = []
    refusal_results = []
    follow_up_subject_results = []

    for entry in entries:
        eid = entry["id"]
        etype = entry["type"]

        if etype in ("answerable", "expected_refusal"):
            question = entry["question"]
            standalone_query, hits, result = run_single_turn(question, [])

            if etype == "answerable":
                judge = judge_answerable(question, entry["reference_answer"], result["answer"], hits)
                answerable_results.append({
                    "id": eid, "question": question, "known_hard": entry.get("known_hard", False),
                    "refused": result["refused"], "answer": result["answer"], **judge,
                })
            else:
                verdict = score_refusal(result["answer"], result["refused"], entry["expected_behavior"])
                refusal_results.append({
                    "id": eid, "question": question, "refused": result["refused"],
                    "answer": result["answer"], **verdict,
                })

        elif etype == "follow_up":
            history: list[dict] = []
            for turn_idx, turn in enumerate(entry["turns"]):
                question = turn["question"]
                standalone_query, hits, result = run_single_turn(question, history)

                subject_check = check_subject_naming(standalone_query, turn.get("subject_keywords", []))
                if subject_check["checked"]:
                    follow_up_subject_results.append({
                        "id": f"{eid}-turn{turn_idx + 1}", "original_question": question, **subject_check,
                    })

                if turn["expected_outcome"] == "answerable":
                    judge = judge_answerable(question, turn["reference_answer"], result["answer"], hits)
                    answerable_results.append({
                        "id": f"{eid}-turn{turn_idx + 1}", "question": question, "known_hard": False,
                        "refused": result["refused"], "answer": result["answer"], **judge,
                    })
                else:
                    verdict = score_refusal(result["answer"], result["refused"], turn["expected_behavior"])
                    refusal_results.append({
                        "id": f"{eid}-turn{turn_idx + 1}", "question": question, "refused": result["refused"],
                        "answer": result["answer"], **verdict,
                    })

                history.append({"role": "user", "content": question})
                history.append({"role": "assistant", "content": result["answer"]})

    return {
        "answerable_results": answerable_results,
        "refusal_results": refusal_results,
        "follow_up_subject_results": follow_up_subject_results,
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
    raw = evaluate()
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
