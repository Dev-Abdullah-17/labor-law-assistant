"""Query rewriting: turn a follow-up question into a standalone query.

Given chat history, a follow-up like "and what about paternity?" needs to
become "How much paternity leave do I get under Sindh labor law?" before
retrieval — otherwise the embedding model has nothing to match against.
Single-turn conversations (no history) skip the LLM call entirely, since
the question is already standalone.

Uses Groq's free tier (llama-3.1-8b-instant — a small, fast model built
for exactly this kind of lightweight task) — see PROGRESS.md for why
Groq over Anthropic/Gemini.
"""

from __future__ import annotations

from groq import Groq

MODEL = "llama-3.1-8b-instant"

SYSTEM_PROMPT = """Rewrite the user's follow-up question into a standalone question that makes sense without the prior conversation, using the chat history for context. Resolve pronouns and implicit references (e.g. "and what about X?" becomes a full question about X in the same context as the prior turn).

Output ONLY the rewritten question, nothing else — no preamble, no explanation."""

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
