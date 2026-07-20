"""Query rewriting: turn a follow-up question into a standalone query, and
translate non-English questions to English before retrieval.

Given chat history, a follow-up like "and what about paternity?" needs to
become "How much paternity leave do I get?" before retrieval — otherwise
the embedding model has nothing to match against. Single-turn conversations
(no history) skip the LLM call entirely, since the question is already
standalone.

Uses Groq's free tier (llama-3.1-8b-instant — a small, fast model built
for exactly this kind of lightweight task) — see PROGRESS.md for why
Groq over Anthropic/Gemini. Translation is the one exception: it uses
the larger openai/gpt-oss-120b model instead (see TRANSLATE_MODEL below).
"""

from __future__ import annotations

import re

from groq import Groq

MODEL = "llama-3.1-8b-instant"

# Milestone 5's Baseline v3 eval caught a real, reproducible bug: the small
# model mistranslated Roman Urdu inconsistently across calls for the exact
# same input (e.g. "tankhwah" (wage) as "temperature" in one run, "minimum
# percentage of votes" in another) — silently sending garbage into
# retrieval with no way to recover downstream. Compared directly against
# openai/gpt-oss-120b (the same model generate_answer already uses) on the
# same 3 Roman Urdu test queries: the larger model translated all 3
# correctly and consistently, the smaller one got all 3 wrong. Unlike query
# rewriting (where an imperfect paraphrase can still retrieve fine),
# translation errors are unrecoverable, so accuracy is worth the extra cost.
TRANSLATE_MODEL = "openai/gpt-oss-120b"

SYSTEM_PROMPT = """Rewrite the user's follow-up question into a standalone question that makes sense without the prior conversation, using the chat history for context. Resolve pronouns and implicit references (e.g. "and what about X?" becomes a full question about X in the same context as the prior turn).

Keep the rewritten question concise. Do NOT add the name of any Act or law unless the user's own follow-up explicitly asks about a specific named Act — restating a full Act name and year when the user didn't ask about one makes the question harder to match against the source documents, not easier.

Output ONLY the rewritten question, nothing else — no preamble, no explanation."""

TRANSLATE_SYSTEM_PROMPT = """Translate the following question to English, preserving its exact meaning as closely as possible. It may be Urdu written in Latin/Roman script (Roman Urdu) or Urdu script.

Output ONLY the translated question in English, nothing else — no preamble, no explanation."""

# Real finding while wiring up translate_to_english: llama-3.1-8b-instant
# does NOT reliably follow an "if already English, return unchanged"
# instruction — it occasionally responds with something like "Please
# provide the rest of the question..." to plain English input, which would
# silently corrupt every English query (the overwhelming majority) before
# it ever reaches retrieval. A cheap, deterministic pre-check — real Urdu
# script, or a short list of distinctive Roman Urdu words unlikely to
# appear in English — decides whether translation is even attempted, so
# the fragile LLM call is only made for input that plausibly needs it.
_URDU_SCRIPT_RE = re.compile("[؀-ۿݐ-ݿ]")
_ROMAN_URDU_MARKERS = {
    "hai", "hain", "kya", "kyun", "kaise", "kitni", "kitne", "zaroori",
    "sakti", "sakta", "nahi", "waqt", "naukri", "tankhwah", "chutti",
    "mulazim", "karobar", "qanoon", "hafton", "mujhe", "meri", "mera",
}
_WORD_RE = re.compile(r"[a-zA-Z]+")


def _needs_translation(text: str) -> bool:
    if _URDU_SCRIPT_RE.search(text):
        return True
    words = {w.lower() for w in _WORD_RE.findall(text)}
    return bool(words & _ROMAN_URDU_MARKERS)


_client: Groq | None = None


def _get_client() -> Groq:
    global _client
    if _client is None:
        _client = Groq()
    return _client


def rewrite_query(question: str, history: list[dict]) -> str:
    """Return a standalone version of `question`, using `history` for context.

    `history` is a list of {"role": "user"|"assistant", "content": str}.
    """
    if not history:
        return question

    history_text = "\n".join(f"{turn['role']}: {turn['content']}" for turn in history)
    completion = _get_client().chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Chat history:\n{history_text}\n\nFollow-up question: {question}",
            },
        ],
    )
    rewritten = (completion.choices[0].message.content or "").strip()
    return rewritten or question


def translate_to_english(question: str) -> str:
    """Translate `question` to English if it needs it — including Roman
    Urdu — before it reaches the embedding-based retriever.

    Milestone 4/5 found (PROGRESS.md) that the multilingual embedding model
    underperforms on this legal corpus even for genuine Urdu script, and
    underperforms further for Roman Urdu specifically — while English
    retrieval is reliably strong. Skips the LLM call entirely (see
    `_needs_translation`) for input that doesn't look like Urdu script or
    Roman Urdu, both to save the call and because the model isn't reliable
    at correctly no-op'ing already-English input.
    """
    if not _needs_translation(question):
        return question

    completion = _get_client().chat.completions.create(
        model=TRANSLATE_MODEL,
        messages=[
            {"role": "system", "content": TRANSLATE_SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ],
    )
    translated = (completion.choices[0].message.content or "").strip()
    return translated or question
