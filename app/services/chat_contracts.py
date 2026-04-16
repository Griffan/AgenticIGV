from __future__ import annotations

import os
from typing import Any, Dict, List, Literal, Optional

from typing_extensions import TypedDict

from pydantic import BaseModel


Mode = Literal["path", "edge"]

# Debug flag for observability logging
DEBUG = os.getenv("AGENTIC_IGV_DEBUG", "0") == "1"


class SampleData(TypedDict, total=False):
    """Per-sample data in multi-BAM edge mode"""
    coverage: List[Dict[str, Any]]
    reads: List[Dict[str, Any]]
    error: str  # Optional error message if extraction failed


class EdgePayload(TypedDict, total=False):
    """Edge payload supports both multi-BAM (samples dict) and single-BAM (flat) formats"""
    # Multi-BAM format: keyed by sample name
    samples: Dict[str, SampleData]
    # Backward-compat flat format (single BAM)
    coverage: List[Dict[str, Any]]
    reads: List[Dict[str, Any]]


class NormalizedChatInput(TypedDict, total=False):
    message: str
    mode: Mode
    region: Optional[str]
    bam_path: str
    coverage: List[Dict[str, Any]]
    reads: List[Dict[str, Any]]
    samples_metadata: List[str]  # Sample names for multi-BAM edge mode


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

    payload = request.edge_payload

    # Check for multi-BAM format (new style with "samples" key)
    if "samples" in payload and payload["samples"]:
        samples_dict = payload["samples"]
        
        if DEBUG:
            print(f"[chat_contracts] Normalizing multi-BAM edge payload with {len(samples_dict)} samples")
        
        if not isinstance(samples_dict, dict):
            raise ContractError("edge_payload.samples must be an object (dict)")
        
        # Validate each sample
        all_coverage = []
        all_reads = []
        sample_names = []
        validation_errors = []
        
        for sample_name, data in samples_dict.items():
            if not isinstance(data, dict):
                raise ContractError(f"edge_payload.samples['{sample_name}'] must be an object")
            
            coverage = data.get("coverage", [])
            reads = data.get("reads", [])
            
            if not isinstance(coverage, list):
                raise ContractError(
                    f"edge_payload.samples['{sample_name}'].coverage must be an array"
                )
            if not isinstance(reads, list):
                raise ContractError(
                    f"edge_payload.samples['{sample_name}'].reads must be an array"
                )
            
            # Validate each coverage item in this sample
            try:
                for item in coverage:
                    _validate_coverage_item(item)
            except ContractError as e:
                # Per-sample error context
                raise ContractError(
                    f"edge_payload.samples['{sample_name}'].coverage validation failed: {str(e)}"
                )

            # Validate each read item in this sample
            try:
                for item in reads:
                    _validate_read_item(item)
            except ContractError as e:
                # Per-sample error context
                raise ContractError(
                    f"edge_payload.samples['{sample_name}'].reads validation failed: {str(e)}"
                )
            
            # Accumulate for normalized output
            all_coverage.extend(coverage)
            all_reads.extend(reads)
            sample_names.append(sample_name)
            
            if DEBUG:
                print(f"  [{sample_name}] coverage={len(coverage)}, reads={len(reads)}")
        
        # Check that at least one sample has data
        if not all_coverage and not all_reads:
            raise ContractError(
                "edge_payload.samples must contain at least one sample with coverage or reads data"
            )
        
        if DEBUG:
            print(f"[chat_contracts] Multi-BAM normalization complete: total_coverage={len(all_coverage)}, total_reads={len(all_reads)}")
        
        normalized["coverage"] = all_coverage
        normalized["reads"] = all_reads
        normalized["samples_metadata"] = sample_names
    else:
        # Backward-compatible flat format (single BAM)
        if DEBUG:
            print(f"[chat_contracts] Normalizing single-BAM edge payload (flat format)")
        
        coverage = payload.get("coverage", [])
        reads = payload.get("reads", [])

        if not isinstance(coverage, list) or not isinstance(reads, list):
            raise ContractError("edge_payload.coverage and edge_payload.reads must be arrays")

        if not coverage and not reads:
            raise ContractError("edge_payload must contain at least one coverage or read item")

        for item in coverage:
            _validate_coverage_item(item)

        for item in reads:
            _validate_read_item(item)

        if DEBUG:
            print(f"  coverage={len(coverage)}, reads={len(reads)}")

        normalized["coverage"] = coverage
        normalized["reads"] = reads

    normalized["bam_path"] = ""
    return normalized
