from pathlib import Path

from fastapi.testclient import TestClient

import app.main as main


RESOURCE_BAM = Path(__file__).resolve().parent.parent / "resource" / "test.bam"


def test_chat_response_serializes_typed_control_resolution_and_compatibility(monkeypatch):
    class DummyGraph:
        def invoke(self, _payload):
            return {
                "response": "Control updated.",
                "coverage": [],
                "reads": [],
                "region": "20:59000-61000",
                "variant_assessment": {},
                "control_resolution": {
                    "preset": "sv",
                    "preset_source": "resource",
                    "preset_path": "resource/igv_presets/sv.json",
                    "base_igv": {"trackHeight": 120, "showCenterGuide": True, "minMapQuality": 20},
                    "resolved_igv": {
                        "trackHeight": 180,
                        "showCenterGuide": True,
                        "minMapQuality": 20,
                        "showNavigation": True,
                    },
                    "applied": [
                        {
                            "key": "preset:sv",
                            "action": "applied",
                            "reason": "Loaded preset asset",
                            "value": "resource/igv_presets/sv.json",
                        },
                        {
                            "key": "trackHeight",
                            "action": "applied",
                            "reason": "Applied direct override",
                            "value": 180,
                        },
                    ],
                    "skipped": [],
                    "failed": [],
                    "parse_notes": [],
                },
            }

    monkeypatch.setattr(main, "_graph", DummyGraph())

    client = TestClient(main.app)
    response = client.post(
        "/api/chat",
        json={
            "message": "switch to sv preset and set trackHeight 180",
            "mode": "path",
            "bam_path": str(RESOURCE_BAM),
            "region": "20:59000-61000",
        },
    )

    assert response.status_code == 200
    payload = response.json()

    # Typed nested payload is present.
    assert payload["control_resolution"]["preset"] == "sv"
    assert payload["control_resolution"]["resolved_igv"]["trackHeight"] == 180
    assert payload["control_resolution"]["applied"][0]["action"] == "applied"

    # Additive compatibility fields are derived from the same typed payload.
    assert payload["igv_params"] == payload["control_resolution"]["resolved_igv"]
    assert payload["preset"] == payload["control_resolution"]["preset"]
    assert "Preset 'sv' applied with overrides" in payload["igv_feedback"]


def test_chat_response_unknown_preset_feedback_uses_typed_control_resolution(monkeypatch):
    class DummyGraph:
        def invoke(self, _payload):
            return {
                "response": "Could not apply preset.",
                "coverage": [],
                "reads": [],
                "control_resolution": {
                    "preset": "nope",
                    "preset_source": "missing",
                    "preset_path": None,
                    "base_igv": {},
                    "resolved_igv": {"trackHeight": 90},
                    "applied": [
                        {
                            "key": "trackHeight",
                            "action": "applied",
                            "reason": "Applied direct override",
                            "value": 90,
                        }
                    ],
                    "skipped": [],
                    "failed": [
                        {
                            "key": "preset:nope",
                            "action": "failed",
                            "reason": "Unknown preset 'nope'",
                            "value": "nope",
                        }
                    ],
                    "parse_notes": [],
                },
            }

    monkeypatch.setattr(main, "_graph", DummyGraph())

    client = TestClient(main.app)
    response = client.post(
        "/api/chat",
        json={
            "message": "switch to nope preset",
            "mode": "path",
            "bam_path": str(RESOURCE_BAM),
            "region": "20:59000-61000",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["control_resolution"]["failed"][0]["key"] == "preset:nope"
    assert payload["igv_feedback"] == "Preset 'nope' not recognized."
    assert payload["igv_params"] == {"trackHeight": 90}


def test_chat_response_user_preset_overlay_compatibility(monkeypatch):
    class DummyGraph:
        def invoke(self, _payload):
            return {
                "response": "User preset overlay applied.",
                "coverage": [],
                "reads": [],
                "control_resolution": {
                    "preset": "sv",
                    "preset_source": "resource",
                    "preset_path": "resource/igv_presets/sv.json",
                    "base_igv": {"trackHeight": 120, "showCenterGuide": True, "minMapQuality": 20},
                    "resolved_igv": {
                        "trackHeight": 160,
                        "showCenterGuide": True,
                        "minMapQuality": 20,
                        "showReadNames": True,
                    },
                    "applied": [
                        {
                            "key": "preset:sv",
                            "action": "applied",
                            "reason": "Loaded preset asset",
                            "value": "resource/igv_presets/sv.json",
                        },
                        {
                            "key": "trackHeight",
                            "action": "applied",
                            "reason": "Applied user preset overlay 'sv'",
                            "value": 160,
                        },
                    ],
                    "skipped": [],
                    "failed": [],
                    "parse_notes": [],
                },
            }

    monkeypatch.setattr(main, "_graph", DummyGraph())

    client = TestClient(main.app)
    response = client.post(
        "/api/chat",
        json={
            "message": "use my sv preset",
            "mode": "path",
            "bam_path": str(RESOURCE_BAM),
            "region": "20:59000-61000",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["igv_params"]["trackHeight"] == 160
    assert payload["preset"] == "sv"
    assert payload["control_resolution"]["resolved_igv"]["showReadNames"] is True


def test_chat_response_rejects_malformed_control_resolution_shape(monkeypatch):
    class DummyGraph:
        def invoke(self, _payload):
            return {
                "response": "Malformed control object.",
                "coverage": [],
                "reads": [],
                "control_resolution": {
                    # Missing required typed fields, should fail validation.
                    "preset": "sv",
                    "resolved_igv": {"trackHeight": 120},
                },
            }

    monkeypatch.setattr(main, "_graph", DummyGraph())

    client = TestClient(main.app)
    response = client.post(
        "/api/chat",
        json={
            "message": "switch to sv preset",
            "mode": "path",
            "bam_path": str(RESOURCE_BAM),
            "region": "20:59000-61000",
        },
    )

    assert response.status_code == 400
    assert "ControlResolutionPayload" in response.json()["detail"]
    assert "preset_source" in response.json()["detail"]


def test_chat_response_igv_feedback_is_readable_not_raw_dict(monkeypatch):
    """igv_feedback must render resolved overrides as key=value pairs, not a dict repr."""

    class DummyGraph:
        def invoke(self, _payload):
            return {
                "response": "Control updated.",
                "coverage": [],
                "reads": [],
                "control_resolution": {
                    "preset": "sv",
                    "preset_source": "resource",
                    "preset_path": "resource/igv_presets/sv.json",
                    "base_igv": {"trackHeight": 120},
                    "resolved_igv": {
                        "trackHeight": 180,
                        "showCenterGuide": True,
                        "showNavigation": False,
                    },
                    "applied": [
                        {
                            "key": "preset:sv",
                            "action": "applied",
                            "reason": "Loaded preset asset",
                            "value": "resource/igv_presets/sv.json",
                        },
                        {
                            "key": "trackHeight",
                            "action": "applied",
                            "reason": "Applied direct override",
                            "value": 180,
                        },
                    ],
                    "skipped": [],
                    "failed": [],
                    "parse_notes": [],
                },
            }

    monkeypatch.setattr(main, "_graph", DummyGraph())

    client = TestClient(main.app)
    response = client.post(
        "/api/chat",
        json={
            "message": "switch to sv preset with trackHeight 180",
            "mode": "path",
            "bam_path": str(RESOURCE_BAM),
            "region": "20:59000-61000",
        },
    )

    assert response.status_code == 200
    feedback = response.json()["igv_feedback"]
    # Must not leak raw dict repr (no braces, no Python-style key quoting).
    assert "{" not in feedback
    assert "}" not in feedback
    assert "'trackHeight'" not in feedback
    # Must contain stable key=value pairs (sorted, booleans lowercased).
    assert "trackHeight=180" in feedback
    assert "showCenterGuide=true" in feedback
    assert "showNavigation=false" in feedback


def test_chat_response_exposes_per_track_variant_assessments(monkeypatch):
    """Multi-BAM responses must surface every track's variant assessment."""

    class DummyGraph:
        def invoke(self, _payload):
            return {
                "response": "Two samples analyzed.",
                "coverage": [],
                "reads": [],
                "per_track_variant_assessments": {
                    "sample_1": {
                        "sv_present": True,
                        "sv_type": "DEL",
                        "confidence": 0.82,
                        "evidence": ["split reads"],
                    },
                    "sample_2": {
                        "sv_present": False,
                        "sv_type": None,
                        "confidence": 0.05,
                        "evidence": [],
                    },
                },
            }

    monkeypatch.setattr(main, "_graph", DummyGraph())

    client = TestClient(main.app)
    response = client.post(
        "/api/chat",
        json={
            "message": "compare samples",
            "mode": "path",
            "bam_path": str(RESOURCE_BAM),
            "region": "20:59000-61000",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert set(payload["per_track_variant_assessments"].keys()) == {"sample_1", "sample_2"}
    assert payload["per_track_variant_assessments"]["sample_1"]["sv_type"] == "DEL"
    assert payload["per_track_variant_assessments"]["sample_2"]["sv_present"] is False
