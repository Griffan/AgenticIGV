from pathlib import Path

import pytest

from app.services.igv_control import (
    load_preset_asset,
    resolve_control_contract,
    resolve_control_request,
    validate_preset_asset,
)
from app.services.igv_control_parser import parse_control_request


RESOURCE_DIR = Path(__file__).resolve().parent.parent / "resource" / "igv_presets"


def test_validate_preset_assets_are_loadable():
    sv, sv_path = load_preset_asset("sv")
    snv, snv_path = load_preset_asset("snv")
    cnv, cnv_path = load_preset_asset("cnv")

    assert sv["name"] == "sv"
    assert snv["name"] == "snv"
    assert cnv["name"] == "cnv"
    assert sv_path == RESOURCE_DIR / "sv.json"
    assert snv_path == RESOURCE_DIR / "snv.json"
    assert cnv_path == RESOURCE_DIR / "cnv.json"


def test_parse_control_request_preserves_unknown_preset_name():
    parsed = parse_control_request("switch to nope preset")

    assert parsed.preset == "nope"
    assert parsed.overrides == {}
    assert parsed.has_control_request is True


def test_parse_control_request_keeps_numeric_track_height_numeric():
    parsed = parse_control_request("use sv preset with trackHeight 180 and show navigation")

    assert parsed.preset == "sv"
    assert parsed.overrides["trackHeight"] == 180
    assert isinstance(parsed.overrides["trackHeight"], int)
    assert parsed.overrides["showNavigation"] is True


def test_parse_control_request_reports_missing_numeric_value_as_note():
    parsed = parse_control_request("sv preset, maybe turn on ruler and track height")

    assert parsed.preset == "sv"
    assert parsed.overrides["showRuler"] is True
    assert any("trackHeight" in note for note in parsed.parse_notes)


def test_resolve_control_request_applies_deterministic_overrides():
    result = resolve_control_request(
        "sv",
        {"trackHeight": 200, "showNavigation": True},
    )

    assert result["preset"] == "sv"
    assert result["resolved_igv"]["trackHeight"] == 200
    assert result["resolved_igv"]["showNavigation"] is True
    assert result["resolved_igv"]["showCenterGuide"] is True
    assert any(item["key"] == "trackHeight" and item["action"] == "applied" for item in result["applied"])
    assert any(item["key"] == "showNavigation" and item["action"] == "applied" for item in result["applied"])


def test_resolve_control_contract_uses_single_source_layering():
    result = resolve_control_contract(
        preset="sv",
        user_presets={"sv": {"trackHeight": 160, "showReadNames": True}},
        direct_overrides={"trackHeight": 180},
        parse_notes=[],
    )

    assert result["base_igv"]["trackHeight"] == 120
    assert result["resolved_igv"]["trackHeight"] == 180
    assert result["resolved_igv"]["showReadNames"] is True
    assert any(item["reason"].startswith("Applied user preset overlay") for item in result["applied"])
    assert any(item["reason"] == "Applied direct override" and item["key"] == "trackHeight" for item in result["applied"])


def test_resolve_control_request_reports_invalid_override_values():
    result = resolve_control_request(
        "snv",
        {"trackHeight": "big", "showReadNames": "yes"},
    )

    assert result["resolved_igv"]["trackHeight"] == 80
    assert result["resolved_igv"]["showReadNames"] is True
    assert any(item["key"] == "trackHeight" and item["action"] == "failed" for item in result["failed"])


def test_resolve_control_request_reports_unknown_preset():
    result = resolve_control_request("nope", {"trackHeight": 90})

    assert result["failed"]
    assert result["preset_source"] == "missing"
    assert any(item["key"] == "preset:nope" and item["action"] == "failed" for item in result["failed"])
    # Unknown preset still permits explicit direct overrides in the same contract.
    assert result["resolved_igv"]["trackHeight"] == 90


def test_load_preset_asset_rejects_traversal_like_name():
    with pytest.raises(FileNotFoundError):
        load_preset_asset("../some/other")


def test_resolve_control_request_uses_repo_relative_preset_path():
    result = resolve_control_request("sv")

    assert result["preset_path"] == "resource/igv_presets/sv.json"
    preset_applied = next(item for item in result["applied"] if item["key"] == "preset:sv")
    assert preset_applied["value"] == "resource/igv_presets/sv.json"


@pytest.mark.parametrize(
    "payload,reason",
    [
        ({"name": "sv"}, "description"),
        ({"name": "sv", "description": "x"}, "igv"),
    ],
)
def test_validate_preset_asset_rejects_malformed_assets(payload, reason):
    with pytest.raises(ValueError) as exc:
        validate_preset_asset(payload, f"broken-{reason}.json")
    assert reason in str(exc.value).lower()


def test_chat_api_exposes_preset_resolution_fields(monkeypatch):
    from app.agents import graph as graph_module

    monkeypatch.setattr(graph_module, "USE_LLM", False)

    result = graph_module.intent_agent({
        "message": "switch to sv preset",
        "mode": "path",
        "bam_path": str(Path(__file__).resolve().parent.parent / "resource" / "test.bam"),
        "region": "20:59000-61000",
    })

    assert result["preset"] == "sv"
    assert result["control_resolution"]["preset"] == "sv"
    assert result["control_resolution"]["preset_source"] == "resource"
    assert result["control_resolution"]["resolved_igv"]["trackHeight"] == 120
    assert result["igv_params"]["trackHeight"] == 120
    assert result["igv_feedback"]


def test_chat_api_exposes_preset_plus_override_resolution(monkeypatch):
    from app.agents import graph as graph_module

    monkeypatch.setattr(graph_module, "USE_LLM", False)

    result = graph_module.intent_agent({
        "message": "use sv preset with trackHeight 180 and show navigation",
        "mode": "path",
        "bam_path": str(Path(__file__).resolve().parent.parent / "resource" / "test.bam"),
        "region": "20:59000-61000",
    })

    assert result["control_resolution"]["resolved_igv"]["trackHeight"] == 180
    assert result["control_resolution"]["resolved_igv"]["showNavigation"] is True
    assert any(item["key"] == "trackHeight" and item["action"] == "applied" for item in result["control_resolution"]["applied"])
    assert result["igv_params"]["trackHeight"] == 180
    assert result["igv_params"]["showNavigation"] is True


def test_chat_api_exposes_partial_control_understanding(monkeypatch):
    from app.agents import graph as graph_module

    monkeypatch.setattr(graph_module, "USE_LLM", False)

    result = graph_module.intent_agent({
        "message": "sv preset, maybe turn on ruler and track height",
        "mode": "path",
        "bam_path": str(Path(__file__).resolve().parent.parent / "resource" / "test.bam"),
        "region": "20:59000-61000",
    })

    assert result["control_resolution"]["preset"] == "sv"
    assert any(item["action"] == "applied" for item in result["control_resolution"]["applied"])
    assert result["control_resolution"]["parse_notes"]
    assert any(item["action"] == "skipped" and item["key"] == "parse_note" for item in result["control_resolution"]["skipped"])


def test_chat_api_reports_invalid_preset_resolution(monkeypatch):
    from app.agents import graph as graph_module

    monkeypatch.setattr(graph_module, "USE_LLM", False)

    result = graph_module.intent_agent({
        "message": "switch to nope preset",
        "mode": "path",
        "bam_path": str(Path(__file__).resolve().parent.parent / "resource" / "test.bam"),
        "region": "20:59000-61000",
    })

    assert result["control_resolution"]["failed"]
    assert result["igv_feedback"] == "Preset 'nope' not recognized."
