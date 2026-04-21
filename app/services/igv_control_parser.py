"""Deterministic natural-language IGV control parsing.

The parser only recognizes the typed control surface and preserves unknown
"<name> preset" references so the resolver can emit explicit failures.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Dict, Optional


BOOLEAN_TRUE_TOKENS = {"true", "on", "yes", "enable", "enabled"}
BOOLEAN_FALSE_TOKENS = {"false", "off", "no", "disable", "disabled"}

NUMERIC_ALIASES: dict[str, list[str]] = {
    "trackHeight": [r"track\s*height", r"trackheight"],
    "minMapQuality": [r"min(?:imum)?\s*map(?:ping)?\s*quality", r"min\s*mapq", r"mapq"],
    "maxInsertSize": [r"max(?:imum)?\s*insert\s*size"],
    "coverageThreshold": [r"coverage\s*threshold"],
}

BOOLEAN_ALIASES: dict[str, list[str]] = {
    "showCenterGuide": [r"show\s*center\s*guide", r"center\s*guide"],
    "showNavigation": [r"show\s*navigation", r"navigation"],
    "showRuler": [r"show\s*ruler", r"ruler"],
    "showReadNames": [r"show\s*read\s*names", r"read\s*names"],
    "colorByStrand": [r"color\s*by\s*strand", r"colour\s*by\s*strand"],
    "viewAsPairs": [r"view\s*as\s*pairs", r"pair(?:ed)?\s*view", r"show\s*pairs", r"pairs?\s*mode"],
}


@dataclass(frozen=True)
class ParsedControlRequest:
    preset: Optional[str]
    overrides: Dict[str, Any]
    parse_notes: list[str]
    has_control_request: bool


def _parse_bool_token(value: str) -> Optional[bool]:
    lowered = value.lower()
    if lowered in BOOLEAN_TRUE_TOKENS:
        return True
    if lowered in BOOLEAN_FALSE_TOKENS:
        return False
    return None


def _extract_preset(text: str) -> Optional[str]:
    # Generic "<name> preset" request. Keep unknown names for explicit resolver failures.
    preset_match = re.search(r"\b([a-z][\w-]*)\s+preset\b", text, re.IGNORECASE)
    if not preset_match:
        return None
    return preset_match.group(1).lower()


def _extract_numeric_overrides(text: str, parse_notes: list[str]) -> Dict[str, int]:
    overrides: Dict[str, int] = {}

    for key, aliases in NUMERIC_ALIASES.items():
        for alias in aliases:
            exact = re.search(rf"\b{key}\b(?:\s*[:=]\s*|\s+)(-?\d+)\b", text, re.IGNORECASE)
            if exact:
                overrides[key] = int(exact.group(1))
                break
            aliased = re.search(rf"\b{alias}\b(?:\s*[:=]\s*|\s+)(-?\d+)\b", text, re.IGNORECASE)
            if aliased:
                overrides[key] = int(aliased.group(1))
                break
            # Known numeric key with no value should be explicit for partial-understanding traces.
            if re.search(rf"\b{alias}\b", text, re.IGNORECASE):
                parse_notes.append(f"Detected numeric key '{key}' without a numeric value")
                break
        if key in overrides:
            continue

    return overrides


def _extract_boolean_overrides(text: str) -> Dict[str, bool]:
    overrides: Dict[str, bool] = {}

    for key, aliases in BOOLEAN_ALIASES.items():
        for alias in aliases:
            explicit_value = re.search(rf"\b{alias}\b\s*(?:[:=]|to)?\s*(true|false|on|off|yes|no|enabled|disabled)\b", text, re.IGNORECASE)
            if explicit_value:
                parsed = _parse_bool_token(explicit_value.group(1))
                if parsed is not None:
                    overrides[key] = parsed
                    break

            mention = re.search(rf"(?:set|enable|disable|turn\s+on|turn\s+off|show|hide|use)?\s*\b{alias}\b", text, re.IGNORECASE)
            if not mention:
                continue

            snippet = mention.group(0).lower()
            if re.search(r"\b(disable|turn\s+off|hide|off|no)\b", snippet):
                overrides[key] = False
            else:
                overrides[key] = True
            break

    return overrides


def parse_control_request(message: str, state_preset: Optional[str] = None) -> ParsedControlRequest:
    text = message or ""
    parse_notes: list[str] = []

    parsed_preset = _extract_preset(text)
    preset = (state_preset or parsed_preset)

    numeric = _extract_numeric_overrides(text, parse_notes)
    boolean = _extract_boolean_overrides(text)
    overrides: Dict[str, Any] = {**boolean, **numeric}

    has_control_request = bool(parsed_preset or state_preset or overrides or parse_notes)

    return ParsedControlRequest(
        preset=preset.lower() if isinstance(preset, str) else None,
        overrides=overrides,
        parse_notes=parse_notes,
        has_control_request=has_control_request,
    )
