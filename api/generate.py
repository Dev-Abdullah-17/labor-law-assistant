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

from groq import Groq

MODEL = "openai/gpt-oss-120b"
REFUSAL_THRESHOLD = 12.0
REFUSAL_MESSAGE = "I could not find this in the ingested laws."
SUPERSEDED_RISK_CAVEAT = (
    "Note: rates in this citation may have been revised since publication — "
    "verify against the latest official notification."
)

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

    if not refused and any(hit["metadata"].get("superseded_risk") for hit in hits):
        answer = f"{answer}\n\n{SUPERSEDED_RISK_CAVEAT}"

    citations = [] if refused else [{**hit["metadata"], "text": hit["text"]} for hit in hits]
    return {"answer": answer, "refused": refused, "citations": citations}
