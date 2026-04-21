from typing import Any, Dict, List, Literal, Optional, TypedDict


class ChatState(TypedDict, total=False):
    message: str
    mode: Literal["path", "edge"]

    bam_path: str
    bam_tracks: List[Dict[str, Any]]
    active_sample_names: List[str]
    per_track_results: Dict[str, Any]

    region: str
    coverage: List[Dict[str, Any]]
    reads: List[Dict[str, Any]]

    response: str
    halt: bool
    route_selection: Literal["control", "analysis"]

    intent: Literal[
        "view_region",
        "analyze_coverage",
        "analyze_reads",
        "analyze_variant",
        "adjust_igv",
        "general_question",
        "unknown",
    ]
    extracted_info: Dict[str, Any]

    variant_assessment: Dict[str, Any]

    igv_params: Optional[Dict[str, Any]]
    igv_feedback: Optional[str]
    preset: Optional[str]
    user_presets: Dict[str, Dict[str, Any]]
    control_resolution: Dict[str, Any]
    control_parse_notes: List[str]
