"""Tests for api.generate — no real Groq API calls."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from api.generate import REFUSAL_MESSAGE, REFUSAL_THRESHOLD, generate_answer


def _hit(score: float, superseded_risk: bool = False, **meta_overrides) -> dict:
    metadata = {
        "act_name": "Sindh Payment of Wages Act",
        "act_year": 2015,
        "section_number": "Section 9",
        "section_title": "Deductions for absence from duty.",
        "page": 8,
        "source_url": "https://example.com/act.pdf",
        "version_date": "2017-03-22",
        "ocr": False,
        "superseded_risk": superseded_risk,
        **meta_overrides,
    }
    return {"score": score, "metadata": metadata, "text": "Deductions may be made under..."}


def _mock_completion(text: str):
    completion = MagicMock()
    completion.choices = [MagicMock(message=MagicMock(content=text))]
    return completion


def test_low_score_refuses_with_no_llm_call():
    hits = [_hit(score=REFUSAL_THRESHOLD + 5)]
    with patch("api.generate._get_client") as mock_get_client:
        result = generate_answer("how do I bake a cake", hits)
    mock_get_client.assert_not_called()
    assert result["refused"] is True
    assert result["answer"] == REFUSAL_MESSAGE
    assert result["citations"] == []


def test_empty_hits_refuses_with_no_llm_call():
    with patch("api.generate._get_client") as mock_get_client:
        result = generate_answer("anything", [])
    mock_get_client.assert_not_called()
    assert result["refused"] is True


def test_high_confidence_hit_calls_llm_and_returns_citations():
    hits = [_hit(score=4.5)]
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _mock_completion(
        "Deductions may be made for absence from duty (Sindh Payment of Wages Act 2015, s. 9, p. 8)."
    )
    with patch("api.generate._get_client", return_value=mock_client):
        result = generate_answer("what deductions are allowed for absence", hits)

    mock_client.chat.completions.create.assert_called_once()
    assert result["refused"] is False
    assert "s. 9" in result["answer"]
    assert result["citations"] == [{**hits[0]["metadata"], "text": hits[0]["text"]}]


def test_llm_refusal_sentence_is_passed_through_as_refused():
    hits = [_hit(score=4.5)]
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _mock_completion(REFUSAL_MESSAGE)
    with patch("api.generate._get_client", return_value=mock_client):
        result = generate_answer("does this act cover paternity leave", hits)

    assert result["refused"] is True
    assert result["answer"] == REFUSAL_MESSAGE
    assert result["citations"] == []


def test_superseded_risk_chunk_gets_caveat_appended():
    hits = [_hit(score=4.5, superseded_risk=True)]
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _mock_completion(
        "The minimum wage is Rs 40,000/month (Sindh Minimum Wages Act 2015, s. Notification, p. 1)."
    )
    with patch("api.generate._get_client", return_value=mock_client):
        result = generate_answer("what is the minimum wage", hits)

    assert result["refused"] is False
    assert "may have been revised" in result["answer"]


def test_non_superseded_risk_chunk_has_no_caveat():
    hits = [_hit(score=4.5, superseded_risk=False)]
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _mock_completion(
        "Deductions may be made for absence (Sindh Payment of Wages Act 2015, s. 9, p. 8)."
    )
    with patch("api.generate._get_client", return_value=mock_client):
        result = generate_answer("what deductions are allowed", hits)

    assert "may have been revised" not in result["answer"]
