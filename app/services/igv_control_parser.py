"""Deterministic natural-language IGV control parsing.

The parser only recognizes the typed control surface and preserves unknown
"<name> preset" references so the resolver can emit explicit failures.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Dict, Optional

from rapidfuzz import process as _rf_process
<<<<<<< Updated upstream
=======

>>>>>>> Stashed changes

BOOLEAN_TRUE_TOKENS = {"true", "on", "yes", "enable", "enabled"}
BOOLEAN_FALSE_TOKENS = {"false", "off", "no", "disable", "disabled"}

FUZZY_MATCH_THRESHOLD: float = 70.0

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

<<<<<<< Updated upstream
# Plain-string aliases for fuzzy matching (no regex metacharacters)
BOOLEAN_PLAIN_ALIASES: dict[str, list[str]] = {
    "viewAsPairs": ["view as pairs", "viewAsPairs", "view pair", "paired view", "show pairs", "pairs mode", "view pairs", "place alignments in pair"],
=======
# Plain-string alias candidates used for fuzzy matching (no regex metacharacters).
BOOLEAN_PLAIN_ALIASES: dict[str, list[str]] = {
    "viewAsPairs": [
        "view as pairs", "viewAsPairs", "view pair", "viewPair", "paired view",
        "show pairs", "pairs mode", "view pairs", "place alignments in pair",
    ],
>>>>>>> Stashed changes
    "showReadNames": ["show read names", "showReadNames", "read names"],
    "showCenterGuide": ["show center guide", "showCenterGuide", "center guide"],
    "showNavigation": ["show navigation", "showNavigation", "navigation"],
    "showRuler": ["show ruler", "showRuler", "ruler"],
    "colorByStrand": ["color by strand", "colorByStrand", "colour by strand"],
}

NUMERIC_PLAIN_ALIASES: dict[str, list[str]] = {
    "trackHeight": ["track height", "trackHeight", "track ht"],
<<<<<<< Updated upstream
    "minMapQuality": ["min map quality", "minMapQuality", "min quality", "min mapq", "mapq", "minimum mapping quality"],
=======
    "minMapQuality": [
        "min map quality", "minMapQuality", "min quality", "min mapq",
        "mapq", "minimum mapping quality",
    ],
>>>>>>> Stashed changes
    "maxInsertSize": ["max insert size", "maxInsertSize", "maximum insert size"],
    "coverageThreshold": ["coverage threshold", "coverageThreshold"],
}

<<<<<<< Updated upstream
# Flat candidate pool: candidate_string -> canonical_key
_OPTION_CANDIDATES: dict[str, str] = {}
for _key, _aliases in BOOLEAN_PLAIN_ALIASES.items():
    _OPTION_CANDIDATES[_key] = _key
    for _alias in _aliases:
        _OPTION_CANDIDATES[_alias] = _key
for _key, _aliases in NUMERIC_PLAIN_ALIASES.items():
    _OPTION_CANDIDATES[_key] = _key
    for _alias in _aliases:
        _OPTION_CANDIDATES[_alias] = _key

=======
# Flat candidate pool: candidate string → canonical key
_OPTION_CANDIDATES: dict[str, str] = {}
for _key, _aliases in BOOLEAN_PLAIN_ALIASES.items():
    for _alias in _aliases:
        _OPTION_CANDIDATES[_alias] = _key
for _key, _aliases in NUMERIC_PLAIN_ALIASES.items():
    for _alias in _aliases:
        _OPTION_CANDIDATES[_alias] = _key

FUZZY_MATCH_THRESHOLD: float = 70.0

>>>>>>> Stashed changes

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


def _normalize_option_key(token: str, parse_notes: list[str]) -> Optional[str]:
<<<<<<< Updated upstream
    """Return the canonical IGV key for *token*, or None if below threshold."""
    result = _rf_process.extractOne(token, _OPTION_CANDIDATES.keys(), score_cutoff=FUZZY_MATCH_THRESHOLD)
=======
    """Return the canonical IGV key for token, or None if below threshold."""
    result = _rf_process.extractOne(
        token, _OPTION_CANDIDATES.keys(), score_cutoff=FUZZY_MATCH_THRESHOLD
    )
>>>>>>> Stashed changes
    if result is None:
        parse_notes.append(
            f"Unrecognized option name '{token}' — no match above threshold {FUZZY_MATCH_THRESHOLD}"
        )
        return None
    best_candidate, _score, _idx = result
    return _OPTION_CANDIDATES[best_candidate]


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

<<<<<<< Updated upstream
    # Fuzzy fallback for unmatched numeric-adjacent tokens
    _BOOL_PATTERN = r"(?:true|false|on|off|yes|no|enabled|disabled)"
    for m in re.finditer(r"(\S+(?:\s+\S+)?)\s*[:=\s]\s*(-?\d+)\b", text, re.IGNORECASE):
        left, value = m.group(1).strip(), m.group(2)
        # Skip if left side is a boolean value token or already matched
        if left.lower() in BOOLEAN_TRUE_TOKENS | BOOLEAN_FALSE_TOKENS:
            continue
        # Skip filler words
        if left.lower() in {"set", "to", "the", "a", "an"}:
            continue
        already_matched = any(left.lower() == k.lower() for k in overrides)
        if already_matched:
            continue
        canonical = _normalize_option_key(left, parse_notes)
        if canonical and canonical not in overrides:
            overrides[canonical] = int(value)
=======
    # Fuzzy fallback: find "<token> <number>" patterns not yet matched
    for m in re.finditer(r"(\S+(?:\s+\S+)?)\s+(-?\d+)\b", text):
        left = m.group(1).strip()
        value = int(m.group(2))
        # Skip stop-words / already-matched
        if left.lower() in {"set", "to", "the", "a", "an"}:
            continue
        canonical = _normalize_option_key(left, parse_notes)
        if canonical and canonical not in overrides and canonical in NUMERIC_PLAIN_ALIASES:
            overrides[canonical] = value
>>>>>>> Stashed changes

    return overrides


def _extract_boolean_overrides(text: str, parse_notes: list[str]) -> Dict[str, bool]:
    overrides: Dict[str, bool] = {}

    for key, aliases in BOOLEAN_ALIASES.items():
        for alias in aliases:
            explicit_value = re.search(
                rf"\b{alias}\b\s*(?:[:=]|to)?\s*(true|false|on|off|yes|no|enabled|disabled)\b",
                text, re.IGNORECASE,
            )
            if explicit_value:
                parsed = _parse_bool_token(explicit_value.group(1))
                if parsed is not None:
                    overrides[key] = parsed
                    break

            mention = re.search(
                rf"(?:set|enable|disable|turn\s+on|turn\s+off|show|hide|use)?\s*\b{alias}\b",
                text, re.IGNORECASE,
            )
            if not mention:
                continue

            snippet = mention.group(0).lower()
            if re.search(r"\b(disable|turn\s+off|hide|off|no)\b", snippet):
                overrides[key] = False
            else:
                overrides[key] = True
            break

<<<<<<< Updated upstream
    # Fuzzy fallback for unmatched boolean-adjacent tokens
    _BOOL_VAL_RE = r"(true|false|on|off|yes|no|enabled|disabled)"
    for m in re.finditer(rf"(\S+(?:\s+\S+)?)\s+{_BOOL_VAL_RE}\b", text, re.IGNORECASE):
        left, bool_str = m.group(1).strip(), m.group(2)
        # Skip filler words
        if left.lower() in {"set", "to", "the", "a", "an", "please"}:
            continue
        # Skip if left side already matched a canonical key
        already_matched = any(left.lower() == k.lower() for k in overrides)
        if already_matched:
            continue
        parsed = _parse_bool_token(bool_str)
        if parsed is None:
            continue
        canonical = _normalize_option_key(left, parse_notes)
        if canonical and canonical not in overrides:
            overrides[canonical] = parsed
=======
    # Fuzzy fallback: find "<token> <bool-value>" patterns not yet matched
    bool_value_pattern = re.compile(
        r"(\S+(?:\s+\S+)?)\s+(true|false|on|off|yes|no|enabled|disabled)\b",
        re.IGNORECASE,
    )
    for m in bool_value_pattern.finditer(text):
        left = m.group(1).strip()
        bool_val = _parse_bool_token(m.group(2))
        if bool_val is None:
            continue
        if left.lower() in {"set", "to", "the", "a", "an"}:
            continue
        canonical = _normalize_option_key(left, parse_notes)
        if canonical and canonical not in overrides and canonical in BOOLEAN_PLAIN_ALIASES:
            overrides[canonical] = bool_val
>>>>>>> Stashed changes

    return overrides


def parse_control_request(message: str, state_preset: Optional[str] = None) -> ParsedControlRequest:
    text = message or ""
    parse_notes: list[str] = []

    parsed_preset = _extract_preset(text)
    preset = (state_preset or parsed_preset)

    numeric = _extract_numeric_overrides(text, parse_notes)
    boolean = _extract_boolean_overrides(text, parse_notes)
    overrides: Dict[str, Any] = {**boolean, **numeric}

    has_control_request = bool(parsed_preset or state_preset or overrides or parse_notes)

    return ParsedControlRequest(
        preset=preset.lower() if isinstance(preset, str) else None,
        overrides=overrides,
        parse_notes=parse_notes,
        has_control_request=has_control_request,
    )
