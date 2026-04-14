from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from typing_extensions import TypedDict

from pydantic import BaseModel


Mode = Literal["path", "edge"]


class EdgePayload(TypedDict, total=False):
    coverage: List[Dict[str, Any]]
    reads: List[Dict[str, Any]]


class NormalizedChatInput(TypedDict, total=False):
    message: str
    mode: Mode
    region: Optional[str]
    bam_path: str
    coverage: List[Dict[str, Any]]
    reads: List[Dict[str, Any]]


class ChatContract(BaseModel):
    message: str
    mode: Mode = "path"
    bam_path: str = ""
    region: Optional[str] = None
    fasta_path: Optional[str] = None
    edge_payload: Optional[EdgePayload] = None


class ContractError(ValueError):
    pass


def _validate_coverage_item(item: Any) -> None:
    if not isinstance(item, dict):
        raise ContractError("coverage items must be objects")
    if "pos" not in item or "depth" not in item:
        raise ContractError("coverage items must include 'pos' and 'depth'")


def _validate_read_item(item: Any) -> None:
    if not isinstance(item, dict):
        raise ContractError("reads items must be objects")
    required_keys = ("name", "start", "end")
    missing = [key for key in required_keys if key not in item]
    if missing:
        raise ContractError(f"reads items must include keys: {', '.join(required_keys)}")


def normalize_chat_request(request: ChatContract) -> NormalizedChatInput:
    normalized: NormalizedChatInput = {
        "message": request.message,
        "mode": request.mode,
        "region": request.region,
    }

    if request.mode == "path":
        normalized["bam_path"] = request.bam_path or ""
        return normalized

    if not (request.region or "").strip():
        raise ContractError("region is required for mode=edge")

    if request.edge_payload is None:
        raise ContractError("edge_payload is required for mode=edge")

    coverage = request.edge_payload.get("coverage", [])
    reads = request.edge_payload.get("reads", [])

    if not isinstance(coverage, list) or not isinstance(reads, list):
        raise ContractError("edge_payload.coverage and edge_payload.reads must be arrays")

    if not coverage and not reads:
        raise ContractError("edge_payload must contain at least one coverage or read item")

    for item in coverage:
        _validate_coverage_item(item)

    for item in reads:
        _validate_read_item(item)

    normalized["coverage"] = coverage
    normalized["reads"] = reads
    normalized["bam_path"] = ""
    return normalized
