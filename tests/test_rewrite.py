"""Tests for api.rewrite — no real Groq API calls."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from api.rewrite import _needs_translation, rewrite_query, translate_to_english


def _mock_completion(text: str):
    completion = MagicMock()
    completion.choices = [MagicMock(message=MagicMock(content=text))]
    return completion


def test_empty_history_skips_llm_call_and_returns_question_unchanged():
    with patch("api.rewrite._get_client") as mock_get_client:
        result = rewrite_query("how much maternity leave do I get?", [])
    mock_get_client.assert_not_called()
    assert result == "how much maternity leave do I get?"


def test_nonempty_history_calls_llm_and_returns_rewritten_query():
    history = [
        {"role": "user", "content": "how much maternity leave do I get?"},
        {"role": "assistant", "content": "Fourteen days (Sindh Shops Act 2015, s. 14, p. 11)."},
    ]
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _mock_completion(
        "How much paternity leave do I get?"
    )
    with patch("api.rewrite._get_client", return_value=mock_client):
        result = rewrite_query("and what about paternity?", history)

    mock_client.chat.completions.create.assert_called_once()
    assert result == "How much paternity leave do I get?"


def test_blank_llm_response_falls_back_to_original_question():
    history = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _mock_completion("")
    with patch("api.rewrite._get_client", return_value=mock_client):
        result = rewrite_query("what about X?", history)

    assert result == "what about X?"


def test_translate_calls_llm_and_returns_english():
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _mock_completion(
        "How much can be deducted from my salary?"
    )
    with patch("api.rewrite._get_client", return_value=mock_client):
        result = translate_to_english("Meri salary se kitni katauti ho sakti hai?")

    mock_client.chat.completions.create.assert_called_once()
    assert result == "How much can be deducted from my salary?"


def test_translate_english_input_skips_llm_call_entirely():
    """Real finding: llama-3.1-8b-instant does not reliably no-op on English
    input when asked to (it sometimes responds with an unrelated
    clarification request instead) — so English-looking input must never
    reach the LLM at all, not just be expected to pass through unchanged."""
    with patch("api.rewrite._get_client") as mock_get_client:
        result = translate_to_english("How much notice is required to terminate an employee?")

    mock_get_client.assert_not_called()
    assert result == "How much notice is required to terminate an employee?"


def test_translate_blank_llm_response_falls_back_to_original_question():
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _mock_completion("")
    with patch("api.rewrite._get_client", return_value=mock_client):
        result = translate_to_english("Naukri se nikalte waqt kitne dinon ka notice zaroori hai?")

    assert result == "Naukri se nikalte waqt kitne dinon ka notice zaroori hai?"


def test_needs_translation_false_for_plain_english():
    assert _needs_translation("How much can be deducted from my salary?") is False


def test_needs_translation_true_for_roman_urdu():
    assert _needs_translation("Meri salary se kitni katauti ho sakti hai?") is True
    assert _needs_translation("Naukri se nikalte waqt kitne dinon ka notice zaroori hai?") is True


def test_needs_translation_true_for_urdu_script():
    assert _needs_translation("میری تنخواہ سے کتنی کٹوتی ہو سکتی ہے؟") is True
