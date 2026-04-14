import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .agents.graph import build_graph
from .services.bam import get_coverage, get_reads
from .services.chat_contracts import ChatContract, ContractError, normalize_chat_request
import pysam


# Load environment variables from project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

APP_ROOT = Path(__file__).resolve().parent
STATIC_DIR = APP_ROOT / "ui" / "static"

app = FastAPI(title="Agentic IGV")


# Debug flag (set AGENTIC_IGV_DEBUG=1 to enable debug prints)
DEBUG = os.getenv("AGENTIC_IGV_DEBUG", "0") == "1"

# Log LLM status on startup
llm_enabled = bool(os.getenv("OPENAI_API_KEY"))
MODEL_NAME = os.getenv("LANGGRAPH_MODEL", "gpt-4o-mini")
BASE_URL = os.getenv("BASE_URL", "https://api.openai.com/v1")
API_KEY = os.getenv("OPENAI_API_KEY")
USE_LLM = bool(os.getenv("OPENAI_API_KEY"))
if DEBUG:
    print(f"\n{'='*60}")
    print("Agentic IGV Starting")
    print(f"LLM Chat: {'ENABLED ✓' if llm_enabled else 'DISABLED (set OPENAI_API_KEY to enable)'}")
    print(f"LLM Model: {MODEL_NAME}")
    print(f"LLM Base URL: {BASE_URL}")
    print(f"{'='*60}\n")

# Add CORS middleware for IGV.js access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Range", "Accept-Ranges", "Content-Length"],
)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

_graph = build_graph()



class ChatRequest(ChatContract):
    bam_path: str = str(PROJECT_ROOT / "resource/test.bam")
    fasta_path: str = str(PROJECT_ROOT / "resource/chr20.fa")



class ChatResponse(BaseModel):
    response: str
    coverage: List[dict]
    reads: List[dict]
    region: Optional[str] = None
    variant_assessment: Dict[str, Any] = Field(default_factory=dict)
    metrics: Dict[str, Any] = Field(default_factory=dict)
    sv_present: Optional[bool] = None
    sv_type: Optional[str] = None
    sv_confidence: Optional[float] = None
    sv_evidence: List[str] = Field(default_factory=list)
    igv_params: Optional[dict] = None
    igv_feedback: Optional[str] = None
    preset: Optional[str] = None



class RegionRequest(BaseModel):
    bam_path: str = str(PROJECT_ROOT / "resource/test.bam")
    region: str
    mode: str = "path"


@app.get("/")
def root() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/bam/chromosomes")
def get_bam_chromosomes(bam_path: str) -> dict:
    """Get chromosome/contig information from BAM header"""
    try:
        if not os.path.isfile(bam_path):
            raise HTTPException(status_code=404, detail="BAM file not found")
        
        with pysam.AlignmentFile(bam_path, "rb") as bam:
            chromosomes = []
            for i, (name, length) in enumerate(zip(bam.references, bam.lengths)):
                chromosomes.append({
                    "name": name,
                    "length": length,
                    "index": i
                })
            return {"chromosomes": chromosomes}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/file")
def get_file(path: str, request: Request):
    if not os.path.isfile(path):
        # Log the error for debugging
        print(f"File not found: {path}")
        raise HTTPException(status_code=404, detail=f"File not found: {path}")
    print(f"Serving file: {path}, Range: {request.headers.get('range', 'none')}")
    return _range_response(path, request)


@app.head("/api/file")
def head_file(path: str):
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="File not found")
    return _head_response(path)


@app.get("/api/index")
def get_index(bam_path: str, request: Request):
    candidates = [bam_path + ".bai"]
    if bam_path.endswith(".bam"):
        candidates.append(bam_path.replace(".bam", ".bai"))

    for candidate in candidates:
        if os.path.isfile(candidate):
            return _range_response(candidate, request)

    raise HTTPException(status_code=404, detail="BAM index (.bai) not found")


@app.head("/api/index")
def head_index(bam_path: str):
    candidates = [bam_path + ".bai"]
    if bam_path.endswith(".bam"):
        candidates.append(bam_path.replace(".bam", ".bai"))

    for candidate in candidates:
        if os.path.isfile(candidate):
            return _head_response(candidate)

    raise HTTPException(status_code=404, detail="BAM index (.bai) not found")


def _range_response(path: str, request: Request):
    range_header = request.headers.get("range")
    
    # Determine media type
    media_type = "application/octet-stream"
    if path.endswith(".bam"):
        media_type = "application/octet-stream"
    elif path.endswith(".bai"):
        media_type = "application/octet-stream"
    elif path.endswith(".fasta") or path.endswith(".fa"):
        media_type = "text/plain; charset=utf-8"
    elif path.endswith(".fai"):
        media_type = "text/plain; charset=utf-8"
    
    if not range_header:
        return FileResponse(path, media_type=media_type)

    size = os.path.getsize(path)
    bytes_unit, _, range_spec = range_header.partition("=")
    if bytes_unit.strip().lower() != "bytes":
        raise HTTPException(status_code=416, detail="Invalid range unit")

    start_str, _, end_str = range_spec.partition("-")
    if not start_str and not end_str:
        raise HTTPException(status_code=416, detail="Invalid range")

    if start_str:
        start = int(start_str)
        end = int(end_str) if end_str else size - 1
    else:
        suffix = int(end_str)
        start = max(size - suffix, 0)
        end = size - 1

    if start >= size or end >= size or start > end:
        raise HTTPException(status_code=416, detail="Range not satisfiable")

    length = end - start + 1

    def iter_file():
        with open(path, "rb") as handle:
            handle.seek(start)
            remaining = length
            while remaining > 0:
                chunk = handle.read(min(8192, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    headers = {
        "Content-Range": f"bytes {start}-{end}/{size}",
        "Accept-Ranges": "bytes",
        "Content-Length": str(length),
    }
    return StreamingResponse(iter_file(), status_code=206, headers=headers, media_type=media_type)


def _head_response(path: str):
    size = os.path.getsize(path)
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(size),
    }
    return StreamingResponse(iter([]), status_code=200, headers=headers)


@app.post("/api/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    if DEBUG:
        print("[DEBUG] /api/chat called")
    try:
        payload = normalize_chat_request(request)
        if DEBUG:
            print(f"[DEBUG] Payload: {payload}")
        result = _graph.invoke(payload)
        if DEBUG:
            print(f"[DEBUG] Agent pipeline result: {result}")
        variant_assessment = result.get("variant_assessment", {}) or {}
        return ChatResponse(
            response=result.get("response", ""),
            coverage=result.get("coverage", []),
            reads=result.get("reads", []),
            region=result.get("region"),
            variant_assessment=variant_assessment,
            metrics=variant_assessment.get("metrics", {}),
            sv_present=variant_assessment.get("sv_present"),
            sv_type=variant_assessment.get("sv_type"),
            sv_confidence=variant_assessment.get("confidence"),
            sv_evidence=variant_assessment.get("evidence", []),
            igv_params=result.get("igv_params"),
            igv_feedback=result.get("igv_feedback"),
            preset=result.get("preset"),
        )
    except ContractError as exc:
        if DEBUG:
            print(f"[DEBUG] ContractError: {exc}")
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        if DEBUG:
            print(f"[DEBUG] Exception: {exc}")
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/region")
def region(request: RegionRequest) -> dict:
    try:
        if request.mode != "path":
            raise HTTPException(status_code=400, detail="/api/region currently supports mode=path only")
        coverage = get_coverage(request.bam_path, request.region)
        reads = get_reads(request.bam_path, request.region)
        return {"coverage": coverage, "reads": reads}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
