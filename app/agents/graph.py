import os
import re
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph

from app.agents.state import ChatState
from app.services.bam import get_coverage, get_reads, summarize_coverage
from app.llm import get_llm_model


# Debug flag (set AGENTIC_IGV_DEBUG=1 to enable debug prints)
DEBUG = os.getenv("AGENTIC_IGV_DEBUG", "0") == "1"

# Load environment variables from project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PROJECT_ROOT / ".env")

REGION_FINDER = re.compile(r"([\w.-]+:\d+[-\.]{1,2}\d+)")
CONTIG_FINDER = re.compile(r"\b(chr\w+|\d+)\b", re.IGNORECASE)
BAM_PATH_FINDER = re.compile(r"([~\w./-]+\.bam)\b", re.IGNORECASE)
USE_LLM = bool(os.getenv("OPENAI_API_KEY"))
VARIANT_KEYWORDS = re.compile(
    r"\b(sv|structural variant|variant|deletion|insertion|duplication|inversion|translocation|breakpoint|fusion)\b",
    re.IGNORECASE,
)
DECOY_CONTIG_HINTS = ("hs37d5", "decoy", "random", "chrUn", "_alt", "_fix", "GL", "KI")


def _pctl(values, fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    index = int(round((len(ordered) - 1) * fraction))
    index = max(0, min(index, len(ordered) - 1))
    return float(ordered[index])


def _load_variant_guide_excerpt() -> str:
    guide_path = Path(__file__).resolve().parent / "IGV_SV_agent_guide.md"
    if not guide_path.exists():
        return "Use IGV SV evidence patterns: soft-clips/split reads, discordant orientation, insert-size shifts, mate-chromosome groups, and coverage context."
    try:
        text = guide_path.read_text(encoding="utf-8")
        return text[:4000]
    except Exception:
        return "Use IGV SV evidence patterns from the local guide."


def _extract_region(text: str) -> Optional[str]:
    match = REGION_FINDER.search(text)
    if not match:
        contig = CONTIG_FINDER.search(text)
        return contig.group(1) if contig else None
    return match.group(1)


def _extract_bam_path(text: str) -> Optional[str]:
    match = BAM_PATH_FINDER.search(text)
    if not match:
        return None
    return match.group(1)


def _extract_bam_paths(text: str) -> list[str]:
    matches = BAM_PATH_FINDER.findall(text)
    # Keep encounter order stable and remove duplicates.
    return list(dict.fromkeys(matches))


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text_value = item.get("text")
                if isinstance(text_value, str):
                    parts.append(text_value)
        return "\n".join(parts)
    return str(content)


def intent_agent(state: ChatState) -> ChatState:
    """Understand user intent, extract region, IGV parameters, and preset requests via LLM or pattern matching."""
    message = state.get("message", "")
    # Try to extract region and BAM path
    region = state.get("region") or _extract_region(message)

    # Extract BAMs from both free text message and bam_path field (which may contain multiple paths).
    extracted_bam_paths = _extract_bam_paths(message)
    extracted_from_bam_field = _extract_bam_paths(state.get("bam_path", ""))
    combined_bam_paths = list(dict.fromkeys(extracted_bam_paths + extracted_from_bam_field))

    bam_path = state.get("bam_path") or (combined_bam_paths[0] if combined_bam_paths else None)
    if bam_path:
        state["bam_path"] = bam_path
    # Materialize bam_tracks from extracted BAM paths when not already provided.
    if combined_bam_paths and not state.get("bam_tracks"):
        state["bam_tracks"] = [
            {
                "bam_path": path,
                "sample_name": f"sample_{i}",
            }
            for i, path in enumerate(combined_bam_paths, start=1)
        ]
    # When multi-track input is available, clear single bam_path to avoid stale/single-path overrides.
    if state.get("bam_tracks"):
        state["bam_path"] = ""

    # --- IGV.js parameter extraction and preset support ---
    # Supported IGV.js parameters and their natural-language aliases
    IGV_PARAM_ALIASES = {
        "trackHeight": [r"track\s*height"],
        "showCenterGuide": [r"show\s*center\s*guide", r"center\s*guide"],
        "showNavigation": [r"show\s*navigation", r"navigation"],
        "showRuler": [r"show\s*ruler", r"ruler"],
        "showReadNames": [r"show\s*read\s*names", r"read\s*names"],
        "colorByStrand": [r"color\s*by\s*strand", r"colour\s*by\s*strand"],
        "minMapQuality": [r"min(?:imum)?\s*map(?:ping)?\s*quality", r"min\s*mapq", r"mapq"],
        "maxInsertSize": [r"max(?:imum)?\s*insert\s*size"],
        "coverageThreshold": [r"coverage\s*threshold"],
        "viewAsPairs": [r"view\s*as\s*pairs", r"pair(?:ed)?\s*view", r"show\s*pairs", r"pairs?\s*mode"],
    }
    IGV_PARAMS = list(IGV_PARAM_ALIASES.keys())
    BUILTIN_PRESETS = {
        "default": {},
        "sv": {"trackHeight": 120, "showCenterGuide": True, "minMapQuality": 20},
        "coverage": {"trackHeight": 80, "showCenterGuide": False, "showRuler": True},
        "reads": {"showReadNames": True, "colorByStrand": True},
    }
    # Extract preset request (simple pattern)
    preset = None
    for key in BUILTIN_PRESETS:
        if key in message.lower():
            preset = key
            break
    # Extract IGV.js parameter changes — camelCase syntax OR natural language aliases
    param_changes = {}

    def _parse_value(raw: str):
        if raw.lower() in ("true", "on", "yes", "enable", "enabled"):
            return True
        if raw.lower() in ("false", "off", "no", "disable", "disabled"):
            return False
        try:
            return int(raw)
        except Exception:
            return raw

    for param, aliases in IGV_PARAM_ALIASES.items():
        # 1. Try exact camelCase: trackHeight: 120 / trackHeight=120
        exact = re.compile(rf"{param}\s*[:=]\s*(\w+)", re.IGNORECASE)
        m = exact.search(message)
        if m:
            param_changes[param] = _parse_value(m.group(1))
            continue
        # 2. Try natural-language aliases with optional value
        for alias in aliases:
            # "set/enable/disable/turn on/turn off <alias>" or "<alias>: value"
            nl_pat = re.compile(
                rf"(?:set|enable|disable|turn\s+on|turn\s+off|show|hide|use)?\s*{alias}"
                rf"(?:\s*[:=]\s*(\w+))?",
                re.IGNORECASE,
            )
            m = nl_pat.search(message)
            if m:
                if m.group(1):
                    param_changes[param] = _parse_value(m.group(1))
                else:
                    # Infer boolean from verb
                    snippet = m.group(0).lower()
                    if re.search(r"\b(disable|turn\s+off|hide|off|no)\b", snippet):
                        param_changes[param] = False
                    else:
                        param_changes[param] = True
                break

    # User-defined preset support (from state)
    user_presets = state.get("user_presets", {})
    if "preset" in state:
        preset = state["preset"]
    if preset and preset in user_presets:
        param_changes.update(user_presets[preset])
    elif preset and preset in BUILTIN_PRESETS:
        param_changes.update(BUILTIN_PRESETS[preset])
    if param_changes:
        state["igv_params"] = param_changes
        state["igv_feedback"] = f"IGV parameters updated: {param_changes}"
    elif preset:
        state["igv_feedback"] = f"Preset '{preset}' recognized, but no parameters found."

    # --- Pattern matching takes priority: if IGV params/preset were resolved, skip LLM ---
    if param_changes or preset:
        state["intent"] = "adjust_igv"
        if region:
            state["region"] = region
        if not state.get("response"):
            state["response"] = state.get("igv_feedback", "IGV settings updated.")
        return state

    # --- End IGV.js parameter extraction ---

    if not USE_LLM:
        # Fallback: simple pattern matching for intent
        if not region:
            state["response"] = "Please provide a region like chr1:100-200 or 20:59000-61000."
            state["halt"] = True
            return state
        state["region"] = region
        if VARIANT_KEYWORDS.search(message or ""):
            state["intent"] = "analyze_variant"
        else:
            state["intent"] = "view_region"
        return state
    # Use LLM to understand intent
    llm = get_llm_model()
    system_prompt = """You are an assistant helping users explore BAM alignment files and adjust IGV.js visualization settings.

Analyze the user's message and determine their intent.

Possible intents:
- view_region: User wants to view a specific genomic region
- analyze_coverage: User asks about coverage/depth statistics
- analyze_reads: User asks about read alignments, quality, or properties
- analyze_variant: User asks whether structural variant evidence exists and what type
- adjust_igv: User wants to change IGV.js visualization parameters or apply a preset
- general_question: General question about the data
- unknown: Cannot determine intent

Extract any genomic region mentioned (format: chr:start-end or just contig:start-end).
Extract any IGV.js parameter changes or preset requests.

Respond in JSON format:
{
  "intent": "<intent_type>",
  "region": "<region if found, else null>",
  "igv_params": {<param: value, ...>},
  "preset": "<preset if found, else null>",
  "reasoning": "<brief explanation>"
}"""
    try:
        response = llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=message)
        ])
        import json
        result = json.loads(_content_to_text(response.content))
        state["intent"] = result.get("intent", "unknown")
        extracted_region = result.get("region")
        if extracted_region:
            state["region"] = extracted_region
        elif region:
            state["region"] = region
        # IGV.js parameter and preset extraction from LLM
        llm_params = result.get("igv_params")
        if isinstance(llm_params, dict) and llm_params:
            state["igv_params"] = llm_params
            state["igv_feedback"] = f"IGV parameters updated: {llm_params}"
        llm_preset = result.get("preset")
        if llm_preset:
            state["preset"] = llm_preset
            # Apply preset if known
            if llm_preset in user_presets:
                state["igv_params"] = user_presets[llm_preset]
                state["igv_feedback"] = f"User preset '{llm_preset}' applied: {user_presets[llm_preset]}"
            elif llm_preset in BUILTIN_PRESETS:
                state["igv_params"] = BUILTIN_PRESETS[llm_preset]
                state["igv_feedback"] = f"Preset '{llm_preset}' applied: {BUILTIN_PRESETS[llm_preset]}"
            else:
                state["igv_feedback"] = f"Preset '{llm_preset}' not recognized."
        state["extracted_info"] = result
    except Exception as e:
        if DEBUG:
            print(f"[DEBUG] intent_agent: LLM exception: {e}")
        # Fallback to simple logic
        if region:
            state["region"] = region
            if VARIANT_KEYWORDS.search(message or ""):
                state["intent"] = "analyze_variant"
            else:
                state["intent"] = "view_region"
        else:
            state["intent"] = "unknown"
    return state


def bam_agent(state: ChatState) -> ChatState:
    """Fetch BAM data for all tracks independently with per-track error isolation"""
    if state.get("halt"):
        return state
    mode = state.get("mode", "path")
    if mode == "edge":
        # Edge mode ships pre-parsed reads/coverage from browser-side parsing.
        state["coverage"] = state.get("coverage", [])
        state["reads"] = state.get("reads", [])
        return state
    
    intent = state.get("intent", "unknown")
    region = state.get("region")
    
    # Check if we need to require a region
    if not region:
        if intent in ["view_region", "analyze_coverage", "analyze_reads", "analyze_variant"]:
            state["response"] = "Please provide a genomic region to analyze."
            state["halt"] = True
        return state
    
    # Get tracks to process — support both multi-BAM and single-BAM (backward compat)
    bam_tracks = state.get("bam_tracks", [])
    
    # If no multi-BAM tracks but single bam_path exists, wrap it for backward compat
    if not bam_tracks and state.get("bam_path"):
        bam_tracks = [
            {
                "bam_path": state.get("bam_path"),
                "sample_name": "sample_1"
            }
        ]
        state["bam_tracks"] = bam_tracks
    
    # If still no tracks, halt
    if not bam_tracks:
        if intent in ["view_region", "analyze_coverage", "analyze_reads", "analyze_variant"]:
            state["response"] = "Please provide a BAM path or BAM tracks to analyze."
            state["halt"] = True
        return state
    
    # Determine which samples are active
    active_sample_names = state.get("active_sample_names", [])
    if not active_sample_names:
        # Default: all samples are active
        active_sample_names = [
            (track.get("sample_name") if isinstance(track, dict) else getattr(track, "sample_name", None))
            or f"sample_{i}"
            for i, track in enumerate(bam_tracks)
        ]
        state["active_sample_names"] = active_sample_names
    
    # Process each track independently with error isolation
    per_track_results: Dict[str, Any] = {}
    analyzed_sample_names: list[str] = []
    
    for track in bam_tracks:
        # Extract track info (handle both dict and TypedDict)
        if isinstance(track, dict):
            sample_name = track.get("sample_name", "unknown")
            bam_path = track.get("bam_path", "")
        else:
            # Assume BamTrack TypedDict-like object
            sample_name = getattr(track, "sample_name", "unknown")
            bam_path = getattr(track, "bam_path", "")
        
        # Skip inactive samples
        if sample_name not in active_sample_names:
            continue
        
        try:
            # Fetch coverage and reads for this track
            coverage = get_coverage(bam_path, region)
            reads = get_reads(bam_path, region)
            
            # Store per-track results
            per_track_results[sample_name] = {
                "bam_path": bam_path,
                "sample_name": sample_name,
                "coverage": coverage,
                "reads": reads,
                "error": None
            }
            analyzed_sample_names.append(sample_name)
        
        except FileNotFoundError as e:
            # BAM file or index not found — isolate error and continue
            error_msg = str(e)
            per_track_results[sample_name] = {
                "bam_path": bam_path,
                "sample_name": sample_name,
                "coverage": [],
                "reads": [],
                "error": error_msg,
                "error_type": "missing_file"
            }
            if DEBUG:
                print(f"[DEBUG] bam_agent: FileNotFoundError for {sample_name}: {error_msg}")
        
        except ValueError as e:
            # Bad region or parsing error
            error_msg = str(e)
            per_track_results[sample_name] = {
                "bam_path": bam_path,
                "sample_name": sample_name,
                "coverage": [],
                "reads": [],
                "error": error_msg,
                "error_type": "bad_region"
            }
            if DEBUG:
                print(f"[DEBUG] bam_agent: ValueError for {sample_name}: {error_msg}")
        
        except Exception as e:
            # Generic error
            error_msg = f"Error processing BAM: {str(e)}"
            per_track_results[sample_name] = {
                "bam_path": bam_path,
                "sample_name": sample_name,
                "coverage": [],
                "reads": [],
                "error": error_msg,
                "error_type": "parse_error"
            }
            if DEBUG:
                print(f"[DEBUG] bam_agent: exception for {sample_name}: {e}")
    
    # Store per-track results in state
    state["per_track_results"] = per_track_results
    
    # Backward compat: expose first analyzed sample at top level
    if analyzed_sample_names:
        first_sample = analyzed_sample_names[0]
        first_result = per_track_results[first_sample]
        state["coverage"] = first_result.get("coverage", [])
        state["reads"] = first_result.get("reads", [])
    else:
        # All tracks failed
        state["coverage"] = []
        state["reads"] = []
        # Don't halt yet — downstream agents can decide what to do
    
    return state


def _analyze_variant_for_reads_coverage(reads: list[Dict[str, Any]], coverage: list[Dict[str, Any]], region: str) -> Dict[str, Any]:
    """Analyze variant evidence from reads and coverage data. Shared logic for per-track and backward-compat analysis."""
    if not reads:
        return {
            "sv_present": False,
            "sv_type": "none",
            "confidence": 0.0,
            "evidence": ["No reads available in current region window."],
            "metrics": {"read_count": 0, "region": region},
        }

    region_contig = region.split(":", 1)[0] if region else ""
    read_count = len(reads)

    soft_clip_reads = sum(1 for r in reads if r.get("has_soft_clip"))
    clipped_ratio = soft_clip_reads / max(read_count, 1)

    insertion_signal_reads = sum(1 for r in reads if (r.get("insertion_bases") or 0) > 0)
    deletion_signal_reads = sum(1 for r in reads if (r.get("deletion_bases") or 0) > 0)

    mate_unmapped = sum(1 for r in reads if r.get("mate_chromosome") == "UNMAPPED")
    def _is_decoy_contig(contig: str) -> bool:
        return any(hint in contig for hint in DECOY_CONTIG_HINTS)

    interchrom_mates = sum(
        1
        for r in reads
        if r.get("is_paired")
        and isinstance(r.get("mate_chromosome"), str)
        and r.get("mate_chromosome") not in (None, "UNMAPPED", "=", region_contig)
        and not _is_decoy_contig(str(r.get("mate_chromosome")))
    )

    paired_reads = [r for r in reads if r.get("is_paired")]
    paired_count = len(paired_reads)
    orientation_counts: Dict[str, int] = {}
    for read in paired_reads:
        orientation = str(read.get("pair_orientation", "UNKNOWN"))
        orientation_counts[orientation] = orientation_counts.get(orientation, 0) + 1

    insert_sizes = [int(r.get("insert_size", 0)) for r in paired_reads if r.get("insert_size")]
    p05 = _pctl(insert_sizes, 0.05)
    p95 = _pctl(insert_sizes, 0.95)
    small_insert_reads = sum(1 for value in insert_sizes if p05 > 0 and value < p05)
    large_insert_reads = sum(1 for value in insert_sizes if p95 > 0 and value > p95)

    coverage_summary = summarize_coverage(coverage)
    cov_mean = float(coverage_summary.get("mean", 0) or 0)
    cov_min = float(coverage_summary.get("min", 0) or 0)
    cov_max = float(coverage_summary.get("max", 0) or 0)
    has_coverage_drop = cov_mean > 0 and cov_min <= cov_mean * 0.35
    has_coverage_gain = cov_mean > 0 and cov_max >= cov_mean * 1.7

    evidence: list[str] = []
    scores: Dict[str, float] = {
        "INS": 0.0,
        "DEL": 0.0,
        "DUP": 0.0,
        "INV": 0.0,
        "BND": 0.0,
    }

    if clipped_ratio >= 0.12:
        scores["INS"] += 0.35
        evidence.append(f"Soft-clipped reads are elevated ({soft_clip_reads}/{read_count}).")
    if insertion_signal_reads / max(read_count, 1) >= 0.08:
        scores["INS"] += 0.25
        evidence.append("Insertion CIGAR signal is present in a subset of reads.")
    if mate_unmapped / max(read_count, 1) >= 0.08:
        scores["INS"] += 0.15
        evidence.append("Reads with unmapped mates are observed near the locus.")

    if has_coverage_drop:
        scores["DEL"] += 0.30
        evidence.append("Coverage drop is observed in the inspected region.")
    if paired_count > 0 and (large_insert_reads / paired_count) >= 0.10:
        scores["DEL"] += 0.30
        evidence.append("Long insert-size discordant pairs are enriched.")
    if deletion_signal_reads / max(read_count, 1) >= 0.08:
        scores["DEL"] += 0.20
        evidence.append("Deletion CIGAR signal is present in a subset of reads.")

    rr_ll = orientation_counts.get("RR", 0) + orientation_counts.get("LL", 0)
    if paired_count > 0 and (rr_ll / paired_count) >= 0.12:
        scores["INV"] += 0.45
        evidence.append("RR/LL discordant pair orientations are enriched.")

    if paired_count > 0 and (interchrom_mates / paired_count) >= 0.10:
        scores["BND"] += 0.60
        evidence.append("Interchromosomal mate mappings are enriched.")

    if paired_count > 0 and (small_insert_reads / paired_count) >= 0.10:
        scores["DUP"] += 0.30
        evidence.append("Short insert-size discordant pairs are enriched.")
    if has_coverage_gain:
        scores["DUP"] += 0.20
        evidence.append("Coverage gain is observed in the inspected region.")

    sorted_scores = sorted(scores.items(), key=lambda pair: pair[1], reverse=True)
    top_type, top_score = sorted_scores[0]
    top_score = float(top_score)
    sv_present = top_score >= 0.45
    sv_type = top_type if sv_present else "none"

    if not evidence:
        evidence.append("No strong discordant-read or coverage signature was detected.")

    return {
        "sv_present": sv_present,
        "sv_type": sv_type,
        "confidence": round(min(1.0, top_score), 2),
        "evidence": evidence[:5],
        "metrics": {
            "read_count": read_count,
            "paired_count": paired_count,
            "soft_clip_ratio": round(clipped_ratio, 3),
            "interchrom_mate_ratio": round(interchrom_mates / max(paired_count, 1), 3),
            "insert_size_p05": round(p05, 1),
            "insert_size_p95": round(p95, 1),
            "small_insert_reads": small_insert_reads,
            "large_insert_reads": large_insert_reads,
            "pair_orientation_RR": orientation_counts.get("RR", 0),
            "pair_orientation_LL": orientation_counts.get("LL", 0),
            "pair_orientation_RL": orientation_counts.get("RL", 0),
            "pair_orientation_LR": orientation_counts.get("LR", 0),
            "score_DEL": round(scores["DEL"], 2),
            "score_INS": round(scores["INS"], 2),
            "score_DUP": round(scores["DUP"], 2),
            "score_INV": round(scores["INV"], 2),
            "coverage_min": cov_min,
            "coverage_mean": cov_mean,
            "coverage_max": cov_max,
        },
        "scores": {key: round(value, 2) for key, value in scores.items()},
    }


def variant_agent(state: ChatState) -> ChatState:
    """Infer SV presence/type from read-level and coverage-level evidence for each BAM independently."""
    if state.get("halt"):
        return state

    region = state.get("region", "")
    per_track_results = state.get("per_track_results", {})
    
    # If we have per-track results, analyze each track independently
    if per_track_results:
        first_successful_assessment = None
        
        for sample_name, track_result in per_track_results.items():
            # Skip tracks with errors
            if track_result.get("error"):
                continue
            
            # Extract reads and coverage for this track
            reads = track_result.get("reads", [])
            coverage = track_result.get("coverage", [])
            
            # Analyze variant evidence for this track
            variant_assessment = _analyze_variant_for_reads_coverage(reads, coverage, region)
            
            # Store per-track variant assessment
            track_result["variant_assessment"] = variant_assessment
            
            # Save first successful assessment for backward compat
            if first_successful_assessment is None:
                first_successful_assessment = variant_assessment
        
        # Backward compat: expose first successful track's assessment at top level
        if first_successful_assessment is not None:
            state["variant_assessment"] = first_successful_assessment
        else:
            # All tracks had errors or no data
            state["variant_assessment"] = {
                "sv_present": False,
                "sv_type": "none",
                "confidence": 0.0,
                "evidence": ["No successful BAM analysis available."],
                "metrics": {"read_count": 0, "region": region},
            }
    else:
        # Fallback for backward compat: single-BAM path (no per_track_results yet)
        reads = state.get("reads", [])
        coverage = state.get("coverage", [])
        
        state["variant_assessment"] = _analyze_variant_for_reads_coverage(reads, coverage, region)
    
    return state


def response_agent(state: ChatState) -> ChatState:
    """Generate intelligent responses with per-track summaries and comparative insights across multiple samples"""
    if state.get("halt"):
        return state
    
    message = state.get("message", "")
    intent = state.get("intent", "unknown")
    region = state.get("region", "")
    
    # Get per-track results if available; otherwise fall back to backward compat
    per_track_results = state.get("per_track_results", {})
    active_sample_names = state.get("active_sample_names", [])
    
    # Build per-track summaries
    track_summaries: Dict[str, Dict[str, Any]] = {}
    analyzed_samples: list[str] = []
    
    if per_track_results:
        # Multi-BAM path: build summaries for each active track
        for sample_name, track_result in per_track_results.items():
            # Filter to active samples
            if active_sample_names and sample_name not in active_sample_names:
                continue
            
            # Check for error
            if track_result.get("error"):
                track_summaries[sample_name] = {
                    "error": track_result.get("error"),
                    "error_type": track_result.get("error_type"),
                    "coverage_stats": None,
                    "read_count": 0,
                    "variant_assessment": None,
                }
                continue
            
            # Extract coverage and reads for this track
            coverage = track_result.get("coverage", [])
            reads = track_result.get("reads", [])
            variant_assessment = track_result.get("variant_assessment", {})
            
            # Build summary for this track
            coverage_stats = summarize_coverage(coverage) if coverage else {}
            read_count = len(reads)
            
            track_summaries[sample_name] = {
                "coverage_stats": coverage_stats,
                "read_count": read_count,
                "coverage_count": len(coverage),
                "variant_assessment": variant_assessment,
                "error": None,
            }
            analyzed_samples.append(sample_name)
    
    if not USE_LLM:
        # Simple fallback response (backward compat + multi-track)
        if track_summaries:
            # Multi-BAM summary (including both analyzed and errored samples)
            response_lines = []
            
            # Add analyzed samples
            if analyzed_samples:
                samples_str = ", ".join(analyzed_samples)
                response_lines.append(f"Analyzed samples: {samples_str}")
                for sample_name in analyzed_samples:
                    summary_info = track_summaries[sample_name]
                    cov_stats = summary_info.get("coverage_stats", {})
                    if cov_stats:
                        response_lines.append(
                            f"{sample_name}: Coverage {cov_stats.get('min', 0)}-{cov_stats.get('max', 0)} "
                            f"(mean {cov_stats.get('mean', 0):.1f}), {summary_info.get('read_count')} reads"
                        )
            
            # Add error samples
            error_samples = {name: info for name, info in track_summaries.items() if info.get("error")}
            if error_samples:
                if analyzed_samples:
                    response_lines.append("Errors:")
                for sample_name, error_info in error_samples.items():
                    response_lines.append(
                        f"{sample_name}: {error_info.get('error')} ({error_info.get('error_type', 'unknown')})"
                    )
            
            state["response"] = "; ".join(response_lines)
        else:
            # Backward compat single-BAM path
            coverage = state.get("coverage", [])
            reads = state.get("reads", [])
            variant_assessment = state.get("variant_assessment", {})
            summary = summarize_coverage(coverage)
            if variant_assessment:
                presence = "present" if variant_assessment.get("sv_present") else "not clearly present"
                sv_type = variant_assessment.get("sv_type", "none")
                state["response"] = (
                    f"Region {region} loaded. Coverage range {summary['min']}-{summary['max']}, mean {summary['mean']}. "
                    f"SV signal is {presence}; likely type: {sv_type}."
                )
            else:
                state["response"] = (
                    f"Region {region} loaded. Coverage range {summary['min']}-{summary['max']}, "
                    f"mean {summary['mean']}. Showing {len(reads)} reads."
                )
        return state
    
    # Use LLM for intelligent responses
    llm = get_llm_model()
    
    # Build context for LLM with per-track summaries and comparative insights
    context_parts = []
    
    if region:
        context_parts.append(f"Genomic region: {region}")
    
    if track_summaries and analyzed_samples:
        # Multi-BAM context: per-track summaries + comparative
        context_parts.append(f"\nAnalyzed samples: {', '.join(analyzed_samples)}")
        context_parts.append("\nPer-track data:")
        
        coverage_means = {}
        read_counts = {}
        sv_types = {}
        
        for sample_name in analyzed_samples:
            summary_info = track_summaries[sample_name]
            cov_stats = summary_info.get("coverage_stats", {})
            read_count = summary_info.get("read_count", 0)
            variant_assess = summary_info.get("variant_assessment", {})
            
            read_counts[sample_name] = read_count
            sv_types[sample_name] = variant_assess.get("sv_type", "none")
            
            if cov_stats:
                mean_cov = cov_stats.get("mean", 0)
                coverage_means[sample_name] = mean_cov
                context_parts.append(
                    f"  {sample_name}: coverage {cov_stats.get('min')}-{cov_stats.get('max')} "
                    f"(mean={mean_cov:.2f}), {read_count} reads, {cov_stats.get('num_points')} coverage points"
                )
            else:
                context_parts.append(f"  {sample_name}: no coverage data")
            
            if variant_assess:
                context_parts.append(
                    f"    {sample_name} variant: sv_present={variant_assess.get('sv_present')}, "
                    f"type={variant_assess.get('sv_type')}, confidence={variant_assess.get('confidence'):.2f}"
                )
                evidence = variant_assess.get("evidence", [])
                if evidence:
                    context_parts.append(f"      Evidence: {'; '.join(evidence[:2])}")
        
        # Add comparative insights
        if len(analyzed_samples) > 1:
            context_parts.append("\nComparative insights:")
            
            # Coverage comparison
            if coverage_means:
                sorted_by_cov = sorted(coverage_means.items(), key=lambda x: x[1], reverse=True)
                if len(sorted_by_cov) > 1:
                    highest = sorted_by_cov[0]
                    lowest = sorted_by_cov[-1]
                    ratio = highest[1] / max(lowest[1], 0.001)
                    context_parts.append(
                        f"  Coverage: {highest[0]} has highest mean coverage ({highest[1]:.2f}), "
                        f"{lowest[0]} has lowest ({lowest[1]:.2f}), ratio {ratio:.1f}x"
                    )
            
            # Read count comparison
            if read_counts:
                sorted_by_reads = sorted(read_counts.items(), key=lambda x: x[1], reverse=True)
                if len(sorted_by_reads) > 1:
                    highest = sorted_by_reads[0]
                    lowest = sorted_by_reads[-1]
                    context_parts.append(
                        f"  Reads: {highest[0]} has {highest[1]} reads, {lowest[0]} has {lowest[1]} reads"
                    )
            
            # SV type comparison
            sv_type_groups = {}
            for sample_name, sv_type in sv_types.items():
                if sv_type not in sv_type_groups:
                    sv_type_groups[sv_type] = []
                sv_type_groups[sv_type].append(sample_name)
            if len(sv_type_groups) > 1:
                sv_summary = "; ".join(f"{sv_type}: {', '.join(samples)}" for sv_type, samples in sv_type_groups.items())
                context_parts.append(f"  SV signals: {sv_summary}")
        
        # Add error info
        errors = {name: info for name, info in track_summaries.items() if info.get("error")}
        if errors:
            context_parts.append("\nErrors encountered:")
            for sample_name, error_info in errors.items():
                context_parts.append(f"  {sample_name}: {error_info.get('error')} ({error_info.get('error_type')})")
    else:
        # Backward compat single-BAM path
        coverage = state.get("coverage", [])
        reads = state.get("reads", [])
        variant_assessment = state.get("variant_assessment", {})
        
        if coverage:
            summary = summarize_coverage(coverage)
            context_parts.append(
                f"Coverage statistics: min={summary['min']}, max={summary['max']}, mean={summary['mean']:.2f}"
            )
            context_parts.append(f"Total coverage points: {len(coverage)}")
        
        if reads:
            context_parts.append(f"Number of reads: {len(reads)}")
            
            # Calculate read statistics
            read_lengths = [r['end'] - r['start'] for r in reads if r.get('end') and r.get('start')]
            if read_lengths:
                avg_len = sum(read_lengths) / len(read_lengths)
                context_parts.append(f"Average read length: {avg_len:.1f}bp")
            
            strands = [r.get('strand', '+') for r in reads]
            plus_strand = strands.count('+')
            minus_strand = strands.count('-')
            context_parts.append(f"Strand distribution: +{plus_strand}, -{minus_strand}")
            
            mapq_values = [r.get('mapq', 0) for r in reads]
            if mapq_values:
                avg_mapq = sum(mapq_values) / len(mapq_values)
                context_parts.append(f"Average mapping quality: {avg_mapq:.1f}")

        if variant_assessment:
            context_parts.append(
                f"Variant assessment: present={variant_assessment.get('sv_present')}, "
                f"type={variant_assessment.get('sv_type')}, confidence={variant_assessment.get('confidence')}"
            )
            evidence = variant_assessment.get("evidence", [])
            if evidence:
                context_parts.append("Variant evidence:\n- " + "\n- ".join(evidence))
            
            metrics = variant_assessment.get("metrics", {})
            if metrics:
                metrics_str = ", ".join(f"{k}={v}" for k, v in metrics.items())
                context_parts.append(f"Metrics: {metrics_str}")
    
    context = "\n".join(context_parts) if context_parts else "No data available."
    
    system_prompt = f"""You are an expert genomics assistant helping users analyze BAM alignment files.
Provide clear, concise, and informative responses about the genomic data.

Use this SV interpretation guidance excerpt when users ask about SV presence/type:
{_load_variant_guide_excerpt()}

When analyzing data:
- Explain what the statistics mean in practical terms
- Point out interesting patterns or potential issues
- Be conversational but accurate
- Keep responses focused and actionable

When analyzing MULTIPLE samples:
- Reference sample names explicitly (e.g., "Sample A has higher coverage than Sample B")
- Highlight comparative insights (coverage differences, variant type variations, read count disparities)
- Clearly indicate which samples were analyzed
- Note any samples with errors separately

When variant evidence exists, explicitly answer:
1) whether SV evidence is present
2) most likely SV type (INS/DEL/DUP/INV/BND) or uncertain
3) top 2-4 evidence points.

If the user asks a question you cannot answer with the available data, explain what information would be needed."""
    
    user_prompt = f"""User question: {message}

Intent: {intent}

Available data:
{context}

Provide a helpful response to the user's question. When multiple samples are analyzed, focus on comparative insights."""
    
    try:
        response = llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ])
        state["response"] = _content_to_text(response.content)
    except Exception as e:
        print(f"LLM response generation failed: {e}")
        # Fallback with multi-track info
        if track_summaries and analyzed_samples:
            samples_str = ", ".join(analyzed_samples)
            fallback_parts = [f"Analyzed samples {samples_str} in region {region}:"]
            for sample_name in analyzed_samples:
                summary_info = track_summaries[sample_name]
                cov_stats = summary_info.get("coverage_stats", {})
                if cov_stats:
                    fallback_parts.append(
                        f"  {sample_name}: Coverage {cov_stats.get('min', 0)}-{cov_stats.get('max', 0)} "
                        f"(mean {cov_stats.get('mean', 0):.1f}), {summary_info.get('read_count')} reads"
                    )
            state["response"] = "; ".join(fallback_parts)
        elif state.get("coverage"):
            coverage = state.get("coverage", [])
            reads = state.get("reads", [])
            summary = summarize_coverage(coverage)
            state["response"] = (
                f"Region {region}: Coverage {summary['min']}-{summary['max']} "
                f"(mean {summary['mean']:.1f}), {len(reads)} reads."
            )
        else:
            state["response"] = "I understood your question but couldn't generate a detailed response. Please try again."
    
    return state


def build_graph() -> Any:
    graph = StateGraph(ChatState)
    graph.add_node("intent_agent", intent_agent)
    graph.add_node("bam_agent", bam_agent)
    graph.add_node("variant_agent", variant_agent)
    graph.add_node("response_agent", response_agent)
    graph.set_entry_point("intent_agent")
    graph.add_edge("intent_agent", "bam_agent")
    graph.add_edge("bam_agent", "variant_agent")
    graph.add_edge("variant_agent", "response_agent")
    graph.add_edge("response_agent", END)
    return graph.compile()
