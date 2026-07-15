"""Answer generation with mandatory citations and a refusal-first design.

Given a question and its retrieved chunks, produce an answer grounded only
in the retrieved text, cited as (Act Name Year, s. N, p. P), or refuse
outright with CLAUDE.md's exact required sentence.

Uses Groq's free tier (openai/gpt-oss-120b) — genuinely no card required,
unlike Anthropic and Gemini, both of which gate even their free tiers
behind a billing account. See PROGRESS.md for the full provider story.

Two independent layers of refusal, because neither alone is reliable:
1. A score-threshold pre-filter (cheap, deterministic) — catches queries
   with no plausible retrieval match at all.
2. An LLM-level instruction to refuse if the retrieved chunks, even though
   they scored well, don't actually answer *this* question. A "leave"
   query can retrieve leave-related chunks by topical similarity without
   any of them addressing the specific thing asked (e.g. maternity leave
   chunks retrieved for a paternity leave question) — see PROGRESS.md.
"""

from __future__ import annotations

import re

from groq import Groq

MODEL = "openai/gpt-oss-120b"
REFUSAL_THRESHOLD = 12.0
REFUSAL_MESSAGE = "I could not find this in the ingested laws."
SUPERSEDED_RISK_CAVEAT = (
    "Note: rates in this citation may have been revised since publication — "
    "verify against the latest official notification."
)

# Matches an "...XYZ Act" phrase in the user's question (e.g. "under the Sindh
# Prohibition of Employment of Children Act") — used only to detect the model
# echoing a question-named Act into its answer when that Act was never
# actually retrieved (see PROGRESS.md, Milestone 4 R8 finding).
QUESTION_ACT_NAME_RE = re.compile(r"([A-Z][A-Za-z\s]{3,80}?\bAct)\b")

SYSTEM_PROMPT = """You are a legal research assistant answering questions about Sindh, Pakistan labor law using only the provided source excerpts.

Rules:
- Answer using ONLY the information in the provided excerpts. Never use outside knowledge.
- Cite every factual claim in the format: (Act Name Year, s. Section Number, p. Page).
- If the excerpts do not actually answer the question — even if they are topically related — respond with exactly this sentence and nothing else: "I could not find this in the ingested laws."
- Do not guess, extrapolate, or fill gaps with assumptions.
- Keep answers concise and directly responsive to the question."""

_client: Groq | None = None


def _get_client() -> Groq:
    global _client
    if _client is None:
        _client = Groq()
    return _client


def _fix_act_name_echo(question: str, answer: str, hits: list[dict]) -> str:
    """Correct the model naming an Act in prose that it never actually
    retrieved, echoed from the user's question instead (e.g. the user asks
    about "the Sindh Prohibition of Employment of Children Act", nothing
    ingested matches, but the model answers from a Shops Act excerpt while
    still calling it by the question's act name in prose).

    Only acts when exactly one retrieved hit's act_name is actually present
    in the answer (an unambiguous, real citation to correct toward) — with
    multiple genuinely-cited acts, guessing which one is "correct" would be
    worse than leaving the text alone.
    """
    hit_act_names = {hit["metadata"]["act_name"] for hit in hits}
    cited_in_answer = [name for name in hit_act_names if name in answer]
    if len(cited_in_answer) != 1:
        return answer
    correct_name = cited_in_answer[0]

    for candidate in QUESTION_ACT_NAME_RE.findall(question):
        candidate = candidate.strip()
        if candidate != correct_name and candidate not in hit_act_names and candidate in answer:
            answer = answer.replace(candidate, correct_name)
    return answer


def _cites_superseded_hit(answer: str, hits: list[dict]) -> bool:
    """True only if a chunk actually named in the answer's text is flagged
    superseded_risk — not merely retrieved-but-unused (see PROGRESS.md,
    Milestone 4 R8 finding: an irrelevant superseded_risk chunk landing in
    the top-5 must not trigger the caveat on an answer that never cites it).
    """
    return any(
        hit["metadata"].get("superseded_risk") and hit["metadata"]["act_name"] in answer
        for hit in hits
    )


def _format_excerpts(hits: list[dict]) -> str:
    parts = []
    for hit in hits:
        meta = hit["metadata"]
        parts.append(
            f"[{meta['act_name']} ({meta['act_year']}), {meta['section_number']} "
            f"— {meta['section_title']}, p.{meta['page']}]\n{hit['text']}"
        )
    return "\n\n---\n\n".join(parts)


def generate_answer(question: str, hits: list[dict]) -> dict:
    """Produce a cited answer or a refusal, given retrieved chunks.

    Returns {"answer": str, "refused": bool, "citations": list[dict]}.
    """
    if not hits or min(hit["score"] for hit in hits) > REFUSAL_THRESHOLD:
        return {"answer": REFUSAL_MESSAGE, "refused": True, "citations": []}

    excerpts = _format_excerpts(hits)
    completion = _get_client().chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Question: {question}\n\nSource excerpts:\n\n{excerpts}"},
        ],
    )
    answer = (completion.choices[0].message.content or "").strip()
    refused = answer == REFUSAL_MESSAGE

    if not refused:
        answer = _fix_act_name_echo(question, answer, hits)
        if _cites_superseded_hit(answer, hits):
            answer = f"{answer}\n\n{SUPERSEDED_RISK_CAVEAT}"

    citations = [] if refused else [{**hit["metadata"], "text": hit["text"]} for hit in hits]
    return {"answer": answer, "refused": refused, "citations": citations}
