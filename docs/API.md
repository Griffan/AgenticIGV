<!-- generated-by: gsd-doc-writer -->
# API Reference

This document provides a reference for all public API endpoints, classes, and methods in the AgenticIGV project. All information is verified directly from the codebase.

## HTTP API Endpoints

### `GET /`
- **Description:** Serves the main static HTML page.
- **Response:** HTML file

### `GET /api/health`
- **Description:** Health check endpoint.
- **Response:** `{ "status": "ok" }`

### `GET /api/bam/chromosomes?bam_path=...`
- **Description:** Returns chromosome/contig information from a BAM file header.
- **Query Parameters:**
  - `bam_path` (str, required): Path to the BAM file.
- **Response:** `{ "chromosomes": [ { "name": str, "length": int, "index": int }, ... ] }`
- **Errors:** 404 if BAM file not found, 400 for other errors.

### `GET /api/file?path=...`
- **Description:** Streams a file (supports HTTP Range requests).
- **Query Parameters:**
  - `path` (str, required): Path to the file.
- **Response:** File stream
- **Errors:** 404 if file not found.

### `HEAD /api/file?path=...`
- **Description:** Returns headers for a file (for range/size checks).
- **Query Parameters:**
  - `path` (str, required): Path to the file.
- **Response:** HTTP headers
- **Errors:** 404 if file not found.

### `GET /api/index?bam_path=...`
- **Description:** Streams the BAM index (.bai) file.
- **Query Parameters:**
  - `bam_path` (str, required): Path to the BAM file.
- **Response:** File stream
- **Errors:** 404 if index not found.

### `HEAD /api/index?bam_path=...`
- **Description:** Returns headers for the BAM index file.
- **Query Parameters:**
  - `bam_path` (str, required): Path to the BAM file.
- **Response:** HTTP headers
- **Errors:** 404 if index not found.

### `POST /api/chat`
- **Description:** Runs a chat-based analysis using the provided request.
- **Request Body:** [`ChatRequest`](#chatrequest)
- **Response:** [`ChatResponse`](#chatresponse)
- **Errors:** 400 for contract or processing errors.

### `POST /api/region`
- **Description:** Returns coverage and reads for a specified region in a BAM file.
- **Request Body:** [`RegionRequest`](#regionrequest)
- **Response:** `{ "coverage": [...], "reads": [...] }`
- **Errors:** 400 for errors, only supports `mode=path`.

---

## Public Classes and Data Models

### `ChatContract` ([app/services/chat_contracts.py](app/services/chat_contracts.py))
- **Fields:**
  - `message: str`
  - `mode: Literal["path", "edge"]` (default: "path")
  - `bam_path: str` (default: "")
  - `region: Optional[str]` (default: None)
  - `fasta_path: Optional[str]` (default: None)
  - `edge_payload: Optional[EdgePayload]` (default: None)

### `ChatRequest` ([app/main.py](app/main.py))
- Inherits from `ChatContract`.

### `ChatResponse` ([app/main.py](app/main.py))
- **Fields:**
  - `response: str`
  - `coverage: List[Dict[str, Any]]`
  - `reads: List[Dict[str, Any]]`
  - `region: Optional[str]`
  - `variant_assessment: Dict[str, Any]`
  - `metrics: Dict[str, Any]`
  - `sv_present: Optional[bool]`
  - `sv_type: Optional[str]`
  - `sv_confidence: Optional[float]`
  - `sv_evidence: List[Any]`

### `RegionRequest` ([app/main.py](app/main.py))
- **Fields:**
  - `bam_path: str`
  - `region: str`
  - `mode: str` (default: "path")

### `EdgePayload` ([app/services/chat_contracts.py](app/services/chat_contracts.py))
- **Fields:**
  - `coverage: List[Dict[str, Any]]`
  - `reads: List[Dict[str, Any]]`

### `NormalizedChatInput` ([app/services/chat_contracts.py](app/services/chat_contracts.py))
- **Fields:**
  - `message: str`
  - `mode: Literal["path", "edge"]`
  - `region: Optional[str]`
  - `bam_path: str`
  - `coverage: List[Dict[str, Any]]`
  - `reads: List[Dict[str, Any]]`

### `ChatState` ([app/agents/state.py](app/agents/state.py))
- **Fields:**
  - `message: str`
  - `mode: Literal["path", "edge"]`
  - `bam_path: str`
  - `region: str`
  - `coverage: List[Dict[str, Any]]`
  - `reads: List[Dict[str, Any]]`
  - `response: str`
  - `halt: bool`
  - `intent: Literal["view_region", "analyze_coverage", "analyze_reads", "analyze_variant", "general_question", "unknown"]`
  - `extracted_info: Dict[str, Any]`
  - `variant_assessment: Dict[str, Any]`

---

## Public Methods and Functions

### BAM Service ([app/services/bam.py](app/services/bam.py))
- `parse_region(region: str) -> Tuple[str, int, int]`: Parse a region string like `chr1:100-200`.
- `ensure_bam_ready(bam_path: str) -> None`: Check BAM and index file existence.
- `get_coverage(bam_path: str, region: str) -> List[Dict[str, Any]]`: Compute coverage for a region.
- `get_reads(bam_path: str, region: str, max_reads: int = 200) -> List[Dict[str, Any]]`: Get reads for a region.
- `summarize_coverage(coverage: List[Dict[str, Any]]) -> Dict[str, Any]`: Summarize coverage data.

### Chat Contracts ([app/services/chat_contracts.py](app/services/chat_contracts.py))
- `normalize_chat_request(request: ChatContract) -> NormalizedChatInput`: Normalize a chat request.

### Agents ([app/agents/graph.py](app/agents/graph.py))
- `intent_agent(state: ChatState) -> ChatState`: Classify user intent and extract region/bam_path.
- `bam_agent(state: ChatState) -> ChatState`: Fetch reads and coverage from BAM.
- `variant_agent(state: ChatState) -> ChatState`: Heuristic scoring for SVs (INS, DEL, DUP, INV, BND).
- `response_agent(state: ChatState) -> ChatState`: Generate LLM answer with metrics and evidence.
- `build_graph() -> Any`: Build the agent graph.

---

All endpoints, classes, and methods above are verified as public and documented in the codebase. No undocumented features are included.
