"""Tests for api.rewrite — no real Groq API calls."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from api.rewrite import rewrite_query


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
        "How much paternity leave do I get under Sindh labor law?"
    )
    with patch("api.rewrite._get_client", return_value=mock_client):
        result = rewrite_query("and what about paternity?", history)

    mock_client.chat.completions.create.assert_called_once()
    assert result == "How much paternity leave do I get under Sindh labor law?"


def test_blank_llm_response_falls_back_to_original_question():
    history = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _mock_completion("")
    with patch("api.rewrite._get_client", return_value=mock_client):
        result = rewrite_query("what about X?", history)

    assert result == "what about X?"
