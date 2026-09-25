"""Tests for the DDInter source URL + filename catalogue."""

from scripts import ddinter_sources


def test_csv_filenames_match_atc_categories():
    # DDInter publishes one CSV per ATC top-level category: all 14.
    # C/G/J/M/N/S were once thought unavailable; they are (measured 2026-09-25).
    expected = {f"ddinter_downloads_code_{c}.csv" for c in "ABCDGHJLMNPRSV"}
    assert set(ddinter_sources.CSV_FILENAMES) == expected


def test_csv_url_for_filename():
    url = ddinter_sources.csv_url("ddinter_downloads_code_A.csv")
    assert url.startswith("https://ddinter2.scbdd.com/")
    assert url.endswith("ddinter_downloads_code_A.csv")


def test_atc_category_from_filename():
    assert ddinter_sources.atc_category("ddinter_downloads_code_A.csv") == "A"
    assert ddinter_sources.atc_category("ddinter_downloads_code_V.csv") == "V"


def test_atc_category_rejects_unknown_filename():
    import pytest
    with pytest.raises(ValueError):
        ddinter_sources.atc_category("garbage.csv")
