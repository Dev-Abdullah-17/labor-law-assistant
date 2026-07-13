"""Tests for the pure-logic scoring helpers in eval.run.

Only the parts that don't require a live LLM call are tested here (matching
the existing project pattern of mocking external calls) — score_refusal,
check_subject_naming, and the aggregation helpers.
"""

from __future__ import annotations

from eval.run import _mean, check_subject_naming, score_refusal, summarize


def test_score_refusal_strict_requires_actual_refusal():
    behavior = {"strict_refusal_required": True}
    assert score_refusal("I could not find this in the ingested laws.", True, behavior)["correct"] is True
    assert score_refusal("Paternity leave is 2 weeks.", False, behavior)["correct"] is False


def test_score_refusal_soft_pass_allows_non_refusal_without_forbidden_pattern():
    behavior = {"strict_refusal_required": False, "fail_regex": "40,?000"}
    # Explains the mechanism without a number -> pass, even though not refused.
    result = score_refusal("Rates are set by Board notification for each category.", False, behavior)
    assert result["correct"] is True
    # States the forbidden figure -> fail, even though it's not the bare refusal sentence.
    result = score_refusal("The rate for Punjab is Rs. 40,000/month.", False, behavior)
    assert result["correct"] is False


def test_score_refusal_soft_pass_still_passes_on_strict_refusal():
    behavior = {"strict_refusal_required": False, "fail_regex": "40,?000"}
    result = score_refusal("I could not find this in the ingested laws.", True, behavior)
    assert result["correct"] is True


def test_check_subject_naming_matches_case_insensitively():
    result = check_subject_naming("How many days of Sick leave are provided?", ["sick"])
    assert result["checked"] is True
    assert result["correct"] is True
    assert result["matched_keywords"] == ["sick"]


def test_check_subject_naming_fails_when_keyword_absent():
    result = check_subject_naming("What about the other benefit?", ["paternity"])
    assert result["correct"] is False


def test_check_subject_naming_skipped_when_no_keywords_given():
    result = check_subject_naming("Some question", [])
    assert result["checked"] is False
    assert result["correct"] is None


def test_mean_ignores_none_values():
    assert _mean([1.0, None, 0.5]) == 0.75
    assert _mean([None, None]) is None
    assert _mean([]) is None


def test_summarize_reports_known_hard_ids_separately_from_failures():
    raw = {
        "answerable_results": [
            {"id": "A1", "known_hard": False, "faithfulness": 1.0, "answer_relevancy": 1.0, "context_precision": 1.0, "context_recall": 1.0},
            {"id": "Q51", "known_hard": True, "faithfulness": 0.0, "answer_relevancy": 0.0, "context_precision": 0.0, "context_recall": 0.0},
        ],
        "refusal_results": [
            {"id": "R1", "correct": True},
            {"id": "R2", "correct": False},
        ],
        "follow_up_subject_results": [
            {"id": "F1-turn2", "correct": True},
        ],
    }
    summary = summarize(raw)
    assert summary["answerable"]["known_hard_ids"] == ["Q51"]
    assert summary["expected_refusal"]["accuracy"] == 0.5
    assert summary["expected_refusal"]["failed_ids"] == ["R2"]
    assert summary["follow_up_subject_naming"]["subject_naming_accuracy"] == 1.0
