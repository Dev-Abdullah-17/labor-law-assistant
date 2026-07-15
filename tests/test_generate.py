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
        "Deductions for absence are proportional to the absence period "
        "(Sindh Payment of Wages Act 2015, s. 9, p. 8)."
    )
    with patch("api.generate._get_client", return_value=mock_client):
        result = generate_answer("what deductions are allowed for absence", hits)

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


def test_superseded_risk_chunk_retrieved_but_not_cited_gets_no_caveat():
    """A real Milestone 4 finding: an irrelevant chunk that happens to be
    superseded_risk=True must not trigger the caveat if the answer never
    actually cites it — only the chunk(s) actually named in the answer's
    text should count."""
    hits = [
        _hit(score=5.0, superseded_risk=False, act_name="Sindh Shops and Commercial Establishments Act"),
        _hit(score=6.7, superseded_risk=True, act_name="Sindh Minimum Wages — Gazette Notification"),
    ]
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _mock_completion(
        "No child may be employed in any establishment for any nature of work "
        "(Sindh Shops and Commercial Establishments Act 2015, s. 20, p. 13)."
    )
    with patch("api.generate._get_client", return_value=mock_client):
        result = generate_answer("child employment rules", hits)

    assert "may have been revised" not in result["answer"]


def test_act_name_echoed_from_question_is_corrected_to_actual_citation():
    """A real Milestone 4 finding (R8): the model named the Act mentioned in
    the user's question in its prose, even though nothing by that name was
    retrieved — the actual citation named a different, real Act. The answer
    should be corrected to consistently name the Act it actually cited."""
    hits = [_hit(score=5.0, act_name="Sindh Shops and Commercial Establishments Act")]
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _mock_completion(
        "The Sindh Prohibition of Employment of Children Act provides that no child "
        "may be employed in any establishment for any nature of work "
        "(Sindh Shops and Commercial Establishments Act 2015, s. 20, p. 13)."
    )
    with patch("api.generate._get_client", return_value=mock_client):
        result = generate_answer(
            "What are the rules for employing children under the Sindh Prohibition "
            "of Employment of Children Act?",
            hits,
        )

    assert "Sindh Prohibition of Employment of Children Act" not in result["answer"]
    assert result["answer"].count("Sindh Shops and Commercial Establishments Act") == 2


def test_act_name_correction_skipped_when_multiple_acts_genuinely_cited():
    """When the answer legitimately cites more than one distinct Act, the
    echo-correction must not guess which one is "correct" — it should leave
    a genuinely multi-source answer untouched."""
    hits = [
        _hit(score=4.0, act_name="Sindh Shops and Commercial Establishments Act"),
        _hit(score=4.2, act_name="Sindh Terms of Employment (Standing Orders) Act"),
    ]
    mock_client = MagicMock()
    text = (
        "One month's notice is required (Sindh Shops and Commercial Establishments Act "
        "2015, s. 19, p. 13), and the same rule applies under the Sindh Terms of "
        "Employment (Standing Orders) Act 2015, Schedule Standing Order 16, p. 15)."
    )
    mock_client.chat.completions.create.return_value = _mock_completion(text)
    with patch("api.generate._get_client", return_value=mock_client):
        result = generate_answer("how much notice is required to terminate an employee", hits)

    assert result["answer"] == text
