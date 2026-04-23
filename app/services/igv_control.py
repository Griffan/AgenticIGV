"""Typed IGV control contract and preset resolution.

Assumption boundary for downstream slices: the allowed override surface is a small,
explicit subset of IGV.js presentation fields that are already exercised by the
current chat flow. New fields should be added here first so the graph and API keep
using a single deterministic contract instead of ad hoc dict merges.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, TypedDict
import json


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PRESET_DIR = PROJECT_ROOT / "resource" / "igv_presets"
PRESET_PUBLIC_DIR = Path("resource") / "igv_presets"


AllowedPresetName = Literal["sv", "snv", "cnv"]
AllowedIgvKey = Literal[
    "trackHeight",
    "showCenterGuide",
    "showNavigation",
    "showRuler",
    "showReadNames",
    "colorByStrand",
    "minMapQuality",
    "maxInsertSize",
    "coverageThreshold",
    "viewAsPairs",
    "showSoftClips",
]


class ControlResult(TypedDict, total=False):
    key: str
    action: Literal["applied", "skipped", "failed"]
    reason: str
    value: Any


class PresetAsset(TypedDict):
    name: AllowedPresetName
    description: str
    igv: Dict[str, Any]


class ControlResolution(TypedDict):
    preset: Optional[str]
    preset_source: str
    preset_path: Optional[str]
    base_igv: Dict[str, Any]
    resolved_igv: Dict[str, Any]
    applied: List[ControlResult]
    skipped: List[ControlResult]
    failed: List[ControlResult]
    parse_notes: List[str]


DEFAULT_BASELINE: Dict[str, Dict[str, Any]] = {
    "sv": {"trackHeight": 120, "showCenterGuide": True, "minMapQuality": 20},
    "snv": {"trackHeight": 80, "showReadNames": True, "colorByStrand": True},
    "cnv": {"trackHeight": 70, "showRuler": True, "coverageThreshold": 20},
}

ALLOWED_OVERRIDE_KEYS = {
    "trackHeight",
    "showCenterGuide",
    "showNavigation",
    "showRuler",
    "showReadNames",
    "colorByStrand",
    "minMapQuality",
    "maxInsertSize",
    "coverageThreshold",
    "viewAsPairs",
    "showSoftClips",
}


def _ensure_bool(value: Any, key: str, failures: List[ControlResult]) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    failures.append({"key": key, "action": "failed", "reason": f"Expected boolean for {key}", "value": value})
    return None


def _ensure_int(value: Any, key: str, failures: List[ControlResult]) -> Optional[int]:
    if isinstance(value, bool):
        failures.append({"key": key, "action": "failed", "reason": f"Expected integer for {key}", "value": value})
        return None
    if isinstance(value, int):
        return value
    failures.append({"key": key, "action": "failed", "reason": f"Expected integer for {key}", "value": value})
    return None


def validate_preset_asset(payload: Any, source: str) -> PresetAsset:
    if not isinstance(payload, dict):
        raise ValueError(f"Preset file {source} must contain a JSON object")
    name = payload.get("name")
    if name not in DEFAULT_BASELINE:
        raise ValueError(f"Preset file {source} has unknown name {name!r}")
    description = payload.get("description")
    igv = payload.get("igv")
    if not isinstance(description, str) or not description:
        raise ValueError(f"Preset file {source} must include a non-empty description")
    if not isinstance(igv, dict):
        raise ValueError(f"Preset file {source} must include an 'igv' object")
    return {"name": name, "description": description, "igv": igv}


def load_preset_asset(name: str) -> tuple[PresetAsset, Path]:
    if name not in DEFAULT_BASELINE:
        raise FileNotFoundError(f"Unknown preset '{name}'")

    preset_path = (PRESET_DIR / f"{name}.json").resolve()
    try:
        preset_path.relative_to(PRESET_DIR.resolve())
    except ValueError as exc:
        raise FileNotFoundError(f"Unknown preset '{name}'") from exc

    if not preset_path.exists():
        raise FileNotFoundError(f"Unknown preset '{name}'")
    try:
        payload = json.loads(preset_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Preset file {preset_path} is invalid JSON: {exc.msg}") from exc
    return validate_preset_asset(payload, str(preset_path)), preset_path


def _validate_override_value(key: str, value: Any, failures: List[ControlResult]) -> Optional[Any]:
    if key in {"trackHeight", "minMapQuality", "maxInsertSize", "coverageThreshold"}:
        return _ensure_int(value, key, failures)
    if key in {"showCenterGuide", "showNavigation", "showRuler", "showReadNames", "colorByStrand", "viewAsPairs"}:
        return _ensure_bool(value, key, failures)
    failures.append({"key": key, "action": "failed", "reason": f"Unsupported override key {key}", "value": value})
    return None


def _load_preset_baseline(
    preset: Optional[str],
    applied: List[ControlResult],
    failed: List[ControlResult],
) -> tuple[Dict[str, Any], str, Optional[str]]:
    if not preset:
        return {}, "none", None

    try:
        preset_asset, preset_path = load_preset_asset(preset)
    except FileNotFoundError:
        failed.append({"key": f"preset:{preset}", "action": "failed", "reason": f"Unknown preset '{preset}'", "value": preset})
        return {}, "missing", None
    except ValueError as exc:
        failed.append({"key": f"preset:{preset}", "action": "failed", "reason": str(exc), "value": preset})
        return {}, "invalid", None

    base_igv = dict(DEFAULT_BASELINE[preset_asset["name"]])
    base_igv.update(preset_asset["igv"])
    preset_path_value = (PRESET_PUBLIC_DIR / f"{preset_asset['name']}.json").as_posix()
    applied.append({
        "key": f"preset:{preset}",
        "action": "applied",
        "reason": "Loaded preset asset",
        "value": preset_path_value,
    })
    return base_igv, "resource", preset_path_value


def _apply_overrides(
    *,
    target: Dict[str, Any],
    overrides: Optional[Dict[str, Any]],
    applied: List[ControlResult],
    skipped: List[ControlResult],
    failed: List[ControlResult],
    reason: str,
) -> None:
    if not overrides:
        return

    for key, value in overrides.items():
        if key not in ALLOWED_OVERRIDE_KEYS:
            skipped.append({
                "key": key,
                "action": "skipped",
                "reason": "Override key is not part of the typed IGV contract",
                "value": value,
            })
            continue

        validated = _validate_override_value(key, value, failed)
        if validated is None:
            continue

        target[key] = validated
        applied.append({"key": key, "action": "applied", "reason": reason, "value": validated})


def resolve_control_contract(
    *,
    preset: Optional[str],
    direct_overrides: Optional[Dict[str, Any]] = None,
    user_presets: Optional[Dict[str, Dict[str, Any]]] = None,
    parse_notes: Optional[List[str]] = None,
) -> ControlResolution:
    applied: List[ControlResult] = []
    skipped: List[ControlResult] = []
    failed: List[ControlResult] = []

    base_igv, preset_source, preset_path_value = _load_preset_baseline(preset, applied, failed)
    resolved = dict(base_igv)

    if preset and user_presets and isinstance(user_presets.get(preset), dict):
        _apply_overrides(
            target=resolved,
            overrides=user_presets[preset],
            applied=applied,
            skipped=skipped,
            failed=failed,
            reason=f"Applied user preset overlay '{preset}'",
        )

    _apply_overrides(
        target=resolved,
        overrides=direct_overrides,
        applied=applied,
        skipped=skipped,
        failed=failed,
        reason="Applied direct override",
    )

    note_items = list(parse_notes or [])
    for note in note_items:
        skipped.append({"key": "parse_note", "action": "skipped", "reason": note})

    return {
        "preset": preset,
        "preset_source": preset_source,
        "preset_path": preset_path_value,
        "base_igv": base_igv,
        "resolved_igv": resolved,
        "applied": applied,
        "skipped": skipped,
        "failed": failed,
        "parse_notes": note_items,
    }


def resolve_control_request(
    preset: str,
    overrides: Optional[Dict[str, Any]] = None,
) -> ControlResolution:
    """Backward-compatible wrapper for preset + override resolution."""
    return resolve_control_contract(preset=preset, direct_overrides=overrides)


def get_known_presets() -> List[str]:
    return sorted(DEFAULT_BASELINE.keys())
