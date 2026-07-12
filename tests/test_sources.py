"""Integrity checks for the document source registry."""

from ingest.sources import SOURCES, core_sources


def test_doc_ids_are_unique() -> None:
    doc_ids = [s.doc_id for s in SOURCES]
    assert len(doc_ids) == len(set(doc_ids))


def test_output_filenames_are_unique() -> None:
    filenames = [s.output_filename for s in SOURCES]
    assert len(filenames) == len(set(filenames))


def test_categories_are_valid() -> None:
    for source in SOURCES:
        assert source.category in {"core", "phase2_skip"}


def test_phase2_sources_have_no_url() -> None:
    for source in SOURCES:
        if source.category == "phase2_skip":
            assert source.url is None


def test_core_sources_returns_only_core() -> None:
    result = core_sources()
    assert result
    assert all(s.category == "core" for s in result)


def test_expected_core_doc_ids_present() -> None:
    expected = {
        "sindh_standing_orders_2015",
        "sindh_shops_commercial_2015",
        "sindh_minimum_wages_2015",
        "sindh_minimum_wages_gazette_latest",
        "sindh_payment_of_wages_2015",
        "sindh_industrial_relations_2013",
        "sindh_maternity_benefits_2018",
    }
    actual = {s.doc_id for s in core_sources()}
    assert actual == expected
