"""Tests for fuzzy-matching behaviour in igv_control_parser."""

import pytest

from app.services.igv_control_parser import parse_control_request


# ---- Case 1: Boolean fuzzy aliases ----

@pytest.mark.parametrize(
    "input_text, expected_key, expected_value",
    [
        ("viewPair true", "viewAsPairs", True),
        ("viewPair false", "viewAsPairs", False),
        ("paired view on", "viewAsPairs", True),
        ("read names off", "showReadNames", False),
    ],
    ids=["viewPair-true", "viewPair-false", "paired-view-on", "read-names-off"],
)
def test_fuzzy_boolean_aliases(input_text, expected_key, expected_value):
    result = parse_control_request(input_text)
    assert expected_key in result.overrides, (
        f"Expected '{expected_key}' in overrides, got {result.overrides}"
    )
    assert result.overrides[expected_key] is expected_value


# ---- Case 2: Numeric fuzzy aliases ----

@pytest.mark.parametrize(
    "input_text, expected_key, expected_value",
    [
        ("set track ht to 80", "trackHeight", 80),
        ("trackHeight 120", "trackHeight", 120),
        ("min mapq 30", "minMapQuality", 30),
    ],
    ids=["track-ht-80", "trackHeight-120", "min-mapq-30"],
)
def test_fuzzy_numeric_aliases(input_text, expected_key, expected_value):
    result = parse_control_request(input_text)
    assert expected_key in result.overrides, (
        f"Expected '{expected_key}' in overrides, got {result.overrides}"
    )
    assert result.overrides[expected_key] == expected_value


# ---- Case 3: Incidental tokens are ignored ----

def test_gibberish_control_like_text_does_not_create_control_request():
    result = parse_control_request("blargopt true")
    assert result.overrides == {}
    assert result.parse_notes == []
    assert result.has_control_request is False


def test_region_phrase_does_not_emit_spurious_parse_notes_or_controls():
    result = parse_control_request("analyze structural variant evidence at 20:59000-61000")
    assert result.overrides == {}
    assert result.parse_notes == []
    assert result.has_control_request is False


# ---- Case 4: Regression — exact match still works ----

def test_existing_exact_match_unaffected():
    result = parse_control_request(
        "use sv preset with trackHeight 180 and show navigation"
    )
    assert result.overrides["trackHeight"] == 180
    assert result.overrides["showNavigation"] is True
    assert result.preset == "sv"
