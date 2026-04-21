import time
import re
import tracemalloc
import concurrent.futures
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from pathlib import Path
from types import SimpleNamespace

import app.main as main
import app.agents.graph as graph_module
from app.services.bam import get_coverage, get_reads


RESOURCE_DIR = Path(__file__).resolve().parent.parent / "resource"
RESOURCE_BAM = RESOURCE_DIR / "test.bam"
RESOURCE_FASTA = RESOURCE_DIR / "chr20.fa"

# Shared fake LLM used for tests that need the graph but not a live LLM
class _FakeLLM:
    def __init__(self, *args, **kwargs):
        pass

    def invoke(self, messages):
        system_prompt = getattr(messages[0], "content", "") if messages else ""
        if "Respond in JSON format" in system_prompt:
            # Return null region so the pre-set request region is preserved
            return SimpleNamespace(
                content='{"intent": "analyze_variant", "region": null, "reasoning": "test stub"}'
            )
        return SimpleNamespace(content="Test stub response from fake LLM.")


def test_health():
    client = TestClient(main.app)
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_file_range(tmp_path):
    sample_path = tmp_path / "sample.bam"
    sample_path.write_bytes(b"abcdef")

    client = TestClient(main.app)
    response = client.get(
        "/api/file",
        params={"path": str(sample_path)},
        headers={"Range": "bytes=1-3"},
    )

    assert response.status_code == 206
    assert response.headers["content-range"].startswith("bytes 1-3/")
    assert response.content == b"bcd"


def test_index_resolution(tmp_path):
    bam_path = tmp_path / "sample.bam"
    bai_path = tmp_path / "sample.bai"
    bam_path.write_bytes(b"bam")
    bai_path.write_bytes(b"bai")

    client = TestClient(main.app)
    response = client.get(
        "/api/index",
        params={"bam_path": str(bam_path)},
        headers={"Range": "bytes=0-1"},
    )

    assert response.status_code == 206
    assert response.content == b"ba"


def test_chat_stubbed(monkeypatch):
    class DummyGraph:
        def invoke(self, payload):
            return {
                "response": "ok",
                "coverage": [],
                "reads": [],
                "region": payload.get("region"),
            }

    monkeypatch.setattr(main, "_graph", DummyGraph())

    client = TestClient(main.app)
    response = client.post(
        "/api/chat",
        json={
            "message": "hello",
            "bam_path": "/tmp/test.bam",
            "region": "chr1:1-2",
        },
    )

    assert response.status_code == 200
    assert response.json()["response"] == "ok"


def test_chat_stubbed_includes_per_track_results(monkeypatch):
    class DummyGraph:
        def invoke(self, payload):
            return {
                "response": "ok",
                "coverage": [{"pos": 1, "depth": 10}],
                "reads": [{"name": "r1", "start": 1, "end": 2}],
                "region": payload.get("region"),
                "bam_tracks": [
                    {"sample_name": "sample_1", "bam_path": "first.bam"},
                    {"sample_name": "sample_2", "bam_path": "second.bam"},
                ],
                "per_track_results": {
                    "sample_1": {
                        "bam_path": "first.bam",
                        "sample_name": "sample_1",
                        "coverage": [{"pos": 1, "depth": 10}],
                        "reads": [{"name": "r1", "start": 1, "end": 2}],
                        "error": None,
                    },
                    "sample_2": {
                        "bam_path": "second.bam",
                        "sample_name": "sample_2",
                        "coverage": [{"pos": 1, "depth": 8}],
                        "reads": [{"name": "r2", "start": 1, "end": 2}],
                        "error": None,
                    },
                },
            }

    monkeypatch.setattr(main, "_graph", DummyGraph())

    client = TestClient(main.app)
    response = client.post(
        "/api/chat",
        json={
            "message": "Load first.bam and second.bam",
            "mode": "path",
            "bam_path": "first.bam",
            "region": "chr1:1-2",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert "bam_tracks" in data
    assert isinstance(data["bam_tracks"], list)
    assert len(data["bam_tracks"]) == 2
    assert data["bam_tracks"][0]["bam_path"] == "first.bam"
    assert data["bam_tracks"][1]["bam_path"] == "second.bam"
    assert "per_track_results" in data
    assert isinstance(data["per_track_results"], dict)
    assert sorted(data["per_track_results"].keys()) == ["sample_1", "sample_2"]
    assert data["per_track_results"]["sample_1"]["bam_path"] == "first.bam"
    assert data["per_track_results"]["sample_2"]["bam_path"] == "second.bam"


def test_chat_edge_mode_with_payload(monkeypatch):
    class DummyGraph:
        def invoke(self, payload):
            assert payload.get("mode") == "edge"
            assert payload.get("region") == "chr1:1-2"
            assert payload.get("coverage") == [{"pos": 1, "depth": 12}]
            assert payload.get("reads") == [{"name": "r1", "start": 1, "end": 2}]
            return {
                "response": "edge-ok",
                "coverage": payload.get("coverage", []),
                "reads": payload.get("reads", []),
                "region": payload.get("region"),
            }

    monkeypatch.setattr(main, "_graph", DummyGraph())

    client = TestClient(main.app)
    response = client.post(
        "/api/chat",
        json={
            "message": "analyze",
            "mode": "edge",
            "region": "chr1:1-2",
            "edge_payload": {
                "coverage": [{"pos": 1, "depth": 12}],
                "reads": [{"name": "r1", "start": 1, "end": 2}],
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["response"] == "edge-ok"


def test_chat_edge_mode_requires_payload(monkeypatch):
    class DummyGraph:
        def invoke(self, _payload):
            return {"response": "should-not-run", "coverage": [], "reads": [], "region": "chr1:1-2"}

    monkeypatch.setattr(main, "_graph", DummyGraph())

    client = TestClient(main.app)
    response = client.post(
        "/api/chat",
        json={
            "message": "analyze",
            "mode": "edge",
            "region": "chr1:1-2",
        },
    )

    assert response.status_code == 400
    assert "edge_payload" in response.json()["detail"].lower()


def test_chat_edge_mode_requires_region(monkeypatch):
    class DummyGraph:
        def invoke(self, _payload):
            return {"response": "should-not-run", "coverage": [], "reads": [], "region": None}

    monkeypatch.setattr(main, "_graph", DummyGraph())

    client = TestClient(main.app)
    response = client.post(
        "/api/chat",
        json={
            "message": "analyze",
            "mode": "edge",
            "edge_payload": {
                "coverage": [{"pos": 1, "depth": 12}],
                "reads": [{"name": "r1", "start": 1, "end": 2}],
            },
        },
    )

    assert response.status_code == 400
    assert "region" in response.json()["detail"].lower()


def test_chat_edge_mode_rejects_empty_payload(monkeypatch):
    class DummyGraph:
        def invoke(self, _payload):
            return {"response": "should-not-run", "coverage": [], "reads": [], "region": "chr1:1-2"}

    monkeypatch.setattr(main, "_graph", DummyGraph())

    client = TestClient(main.app)
    response = client.post(
        "/api/chat",
        json={
            "message": "analyze",
            "mode": "edge",
            "region": "chr1:1-2",
            "edge_payload": {"coverage": [], "reads": []},
        },
    )

    assert response.status_code == 400
    assert "at least one" in response.json()["detail"].lower()


def test_chat_edge_mode_rejects_invalid_item_schema(monkeypatch):
    class DummyGraph:
        def invoke(self, _payload):
            return {"response": "should-not-run", "coverage": [], "reads": [], "region": "chr1:1-2"}

    monkeypatch.setattr(main, "_graph", DummyGraph())

    client = TestClient(main.app)
    response = client.post(
        "/api/chat",
        json={
            "message": "analyze",
            "mode": "edge",
            "region": "chr1:1-2",
            "edge_payload": {
                "coverage": [{"depth": 9}],
                "reads": [{"name": "r1", "start": 1, "end": 2}],
            },
        },
    )

    assert response.status_code == 400
    assert "coverage items" in response.json()["detail"].lower()


def test_chat_edge_mode_real_graph_integration(monkeypatch):
    if graph_module.USE_LLM:
        monkeypatch.setattr(graph_module, "get_llm_model", lambda: _FakeLLM())

    client = TestClient(main.app)
    response = client.post(
        "/api/chat",
        json={
            "message": "analyze structural variant evidence",
            "mode": "edge",
            "region": "chr1:1-100",
            "edge_payload": {
                "coverage": [
                    {"pos": 1, "depth": 20},
                    {"pos": 2, "depth": 10},
                    {"pos": 3, "depth": 22},
                ],
                "reads": [
                    {
                        "name": "r1",
                        "start": 1,
                        "end": 70,
                        "has_soft_clip": True,
                        "insertion_bases": 5,
                        "deletion_bases": 0,
                        "is_paired": True,
                        "mate_chromosome": "chr2",
                        "pair_orientation": "LR",
                        "insert_size": 800,
                    }
                ],
            },
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["region"] == "chr1:1-100"
    assert isinstance(data["variant_assessment"], dict)
    assert "sv_present" in data


def test_bam_chromosomes(tmp_path):
    # Create a minimal BAM file with header
    bam_path = tmp_path / "test.bam"
    
    import pysam
    header = {
        "HD": {"VN": "1.0"},
        "SQ": [
            {"SN": "chr1", "LN": 100000},
            {"SN": "chr2", "LN": 200000},
        ]
    }
    with pysam.AlignmentFile(str(bam_path), "wb", header=header) as _:
        pass
    
    client = TestClient(main.app)
    response = client.get(
        "/api/bam/chromosomes",
        params={"bam_path": str(bam_path)}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert len(data["chromosomes"]) == 2
    assert data["chromosomes"][0]["name"] == "chr1"
    assert data["chromosomes"][0]["length"] == 100000
    assert data["chromosomes"][1]["name"] == "chr2"
    assert data["chromosomes"][1]["length"] == 200000


def test_smoke_resource_bam_chromosomes_api():
    assert RESOURCE_BAM.exists(), f"Missing smoke fixture: {RESOURCE_BAM}"

    client = TestClient(main.app)
    response = client.get("/api/bam/chromosomes", params={"bam_path": str(RESOURCE_BAM)})

    assert response.status_code == 200
    payload = response.json()
    assert "chromosomes" in payload
    assert isinstance(payload["chromosomes"], list)
    assert len(payload["chromosomes"]) > 0


def test_smoke_resource_file_serving_api():
    assert RESOURCE_BAM.exists(), f"Missing smoke fixture: {RESOURCE_BAM}"
    assert RESOURCE_FASTA.exists(), f"Missing smoke fixture: {RESOURCE_FASTA}"

    client = TestClient(main.app)

    bam_response = client.get(
        "/api/file",
        params={"path": str(RESOURCE_BAM)},
        headers={"Range": "bytes=0-63"},
    )
    assert bam_response.status_code == 206
    assert bam_response.headers["content-range"].startswith("bytes 0-63/")

    fasta_response = client.get(
        "/api/file",
        params={"path": str(RESOURCE_FASTA)},
        headers={"Range": "bytes=0-31"},
    )
    assert fasta_response.status_code == 206
    assert fasta_response.headers["content-range"].startswith("bytes 0-31/")


def test_smoke_resource_chat_path_mode(monkeypatch):
    """Smoke test: path mode chat with the real BAM file (LLM stubbed for determinism)."""
    assert RESOURCE_BAM.exists(), f"Missing smoke fixture: {RESOURCE_BAM}"

    if graph_module.USE_LLM:
        monkeypatch.setattr(graph_module, "get_llm_model", lambda: _FakeLLM())

    client = TestClient(main.app)
    response = client.post(
        "/api/chat",
        json={
            "message": "analyze this region",
            "mode": "path",
            "bam_path": str(RESOURCE_BAM),
            "region": "20:59000-61000",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert "response" in data
    assert isinstance(data.get("coverage", []), list)
    assert isinstance(data.get("reads", []), list)


def test_chat_igv_parameter_adjustment(monkeypatch):
    """IGV parameter changes in chat message are extracted and returned in response."""
    import app.agents.graph as graph_module

    # Disable LLM to test pattern-matching path
    monkeypatch.setattr(graph_module, "USE_LLM", False)

    client = TestClient(main.app)
    response = client.post(
        "/api/chat",
        json={
            "message": "set trackHeight: 120 for the view",
            "mode": "path",
            "bam_path": str(RESOURCE_BAM),
            "region": "20:59000-61000",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data.get("igv_params") is not None, "Expected igv_params in response"
    assert data["igv_params"].get("trackHeight") == 120
    assert data.get("igv_feedback") is not None


def test_chat_igv_parameter_natural_language(monkeypatch):
    """Natural language phrases like 'view as pairs' are extracted as IGV params."""
    import app.agents.graph as graph_module

    monkeypatch.setattr(graph_module, "USE_LLM", False)

    client = TestClient(main.app)
    response = client.post(
        "/api/chat",
        json={
            "message": "enable view as pairs",
            "mode": "path",
            "bam_path": str(RESOURCE_BAM),
            "region": "20:59000-61000",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data.get("igv_params") is not None, "Expected igv_params for 'view as pairs'"
    assert data["igv_params"].get("viewAsPairs") is True

    # Also test "show read names"
    response2 = client.post(
        "/api/chat",
        json={
            "message": "show read names",
            "mode": "path",
            "bam_path": str(RESOURCE_BAM),
            "region": "20:59000-61000",
        },
    )
    assert response2.status_code == 200
    data2 = response2.json()
    assert data2.get("igv_params", {}).get("showReadNames") is True


def test_chat_igv_presets(monkeypatch):
    """Built-in preset names in chat message are applied and returned in response."""
    import app.agents.graph as graph_module

    monkeypatch.setattr(graph_module, "USE_LLM", False)

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

    assert response.status_code == 200
    data = response.json()
    # sv preset sets trackHeight to 120 and minMapQuality to 20
    assert data.get("igv_params") is not None, "Expected igv_params for preset"
    assert data["igv_params"].get("trackHeight") == 120
    assert data.get("igv_feedback") is not None


def test_chat_control_resolution_preset_plus_override(monkeypatch):
    """API: preset+override request returns control_resolution with applied/skipped/failed in serialized response."""
    monkeypatch.setattr(graph_module, "USE_LLM", False)

    client = TestClient(main.app)
    response = client.post(
        "/api/chat",
        json={
            "message": "use sv preset with trackHeight 180 and show navigation",
            "mode": "path",
            "bam_path": str(RESOURCE_BAM),
            "region": "20:59000-61000",
        },
    )

    assert response.status_code == 200
    data = response.json()
    cr = data.get("control_resolution")
    assert cr is not None, "Expected control_resolution in API response"
    assert cr["preset"] == "sv"
    assert cr["preset_source"] == "resource"
    assert cr["resolved_igv"]["trackHeight"] == 180
    assert cr["resolved_igv"]["showNavigation"] is True
    # applied list must include preset and both overrides
    applied_keys = [item["key"] for item in cr["applied"]]
    assert "preset:sv" in applied_keys
    assert "trackHeight" in applied_keys
    assert "showNavigation" in applied_keys
    assert cr["failed"] == []
    # Compatibility fields derived from control_resolution
    assert data["igv_params"]["trackHeight"] == 180
    assert data["preset"] == "sv"


def test_chat_control_resolution_partial_understanding(monkeypatch):
    """API: partially understood input returns control_resolution with parse_notes and skipped items."""
    monkeypatch.setattr(graph_module, "USE_LLM", False)

    client = TestClient(main.app)
    response = client.post(
        "/api/chat",
        json={
            "message": "sv preset, maybe turn on ruler and track height",
            "mode": "path",
            "bam_path": str(RESOURCE_BAM),
            "region": "20:59000-61000",
        },
    )

    assert response.status_code == 200
    data = response.json()
    cr = data.get("control_resolution")
    assert cr is not None, "Expected control_resolution in API response"
    assert cr["preset"] == "sv"
    assert len(cr["parse_notes"]) > 0, "Partial understanding should surface parse_notes"
    # Skipped items should include the parse_note entries
    skipped_keys = [item["key"] for item in cr["skipped"]]
    assert "parse_note" in skipped_keys, "parse_notes must appear as skipped items"
    # Ruler override was understood
    assert cr["resolved_igv"]["showRuler"] is True


def test_chat_control_resolution_invalid_preset(monkeypatch):
    """API: invalid preset name returns control_resolution with failed entry and error feedback."""
    monkeypatch.setattr(graph_module, "USE_LLM", False)

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
    data = response.json()
    cr = data.get("control_resolution")
    assert cr is not None, "Expected control_resolution in API response"
    assert cr["preset"] == "nope"
    assert cr["preset_source"] == "missing"
    failed_keys = [item["key"] for item in cr["failed"]]
    assert "preset:nope" in failed_keys, "Invalid preset must appear in failed list"
    assert "not recognized" in data["igv_feedback"].lower()


def test_chat_igv_ambiguous_no_silent_failure(monkeypatch):
    """Unsupported/ambiguous chat message does not silently fail; response is always non-empty."""
    import app.agents.graph as graph_module

    monkeypatch.setattr(graph_module, "USE_LLM", False)

    client = TestClient(main.app)
    response = client.post(
        "/api/chat",
        json={
            "message": "do something unrecognizable xyzzy",
            "mode": "path",
            "bam_path": str(RESOURCE_BAM),
            "region": "20:59000-61000",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data.get("response") is not None and data["response"] != ""



def test_chat_path_and_edge_parity(monkeypatch):
    assert RESOURCE_BAM.exists(), f"Missing smoke fixture: {RESOURCE_BAM}"

    if graph_module.USE_LLM:
        monkeypatch.setattr(graph_module, "get_llm_model", lambda: _FakeLLM())

    region = "20:59000-61000"
    client = TestClient(main.app)

    edge_payload = {
        "coverage": get_coverage(str(RESOURCE_BAM), region),
        "reads": get_reads(str(RESOURCE_BAM), region),
    }

    path_response = client.post(
        "/api/chat",
        json={
            "message": "analyze structural variant evidence",
            "mode": "path",
            "bam_path": str(RESOURCE_BAM),
            "region": region,
        },
    )
    edge_response = client.post(
        "/api/chat",
        json={
            "message": "analyze structural variant evidence",
            "mode": "edge",
            "region": region,
            "edge_payload": edge_payload,
        },
    )

    assert path_response.status_code == 200
    assert edge_response.status_code == 200

    path_data = path_response.json()
    edge_data = edge_response.json()

    assert path_data["region"] == edge_data["region"] == region
    assert path_data.get("coverage") == edge_data.get("coverage") == edge_payload["coverage"]
    assert path_data.get("reads") == edge_data.get("reads") == edge_payload["reads"]
    assert path_data.get("variant_assessment") == edge_data.get("variant_assessment")
    assert path_data.get("sv_present") == edge_data.get("sv_present")
    assert path_data.get("sv_type") == edge_data.get("sv_type")
    assert path_data.get("sv_confidence") == edge_data.get("sv_confidence")
    assert path_data.get("sv_evidence") == edge_data.get("sv_evidence")

def test_chat_igv_params_and_feedback(monkeypatch):
    class DummyGraph:
        def invoke(self, payload):
            # Simulate backend extracting IGV params and preset
            return {
                "response": "Parameters updated.",
                "igv_params": {"trackHeight": 150, "showReadNames": True},
                "igv_feedback": "IGV parameters updated: {'trackHeight': 150, 'showReadNames': True}",
                "preset": "sv",
                "region": payload.get("region", "chr1:1-2"),
            }

    monkeypatch.setattr(main, "_graph", DummyGraph())

    client = TestClient(main.app)
    response = client.post(
        "/api/chat",
        json={
            "message": "Set trackHeight:150 and showReadNames:true, use sv preset",
            "bam_path": "/tmp/test.bam",
            "region": "chr1:1-2",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["igv_params"] == {"trackHeight": 150, "showReadNames": True}
    assert data["igv_feedback"].startswith("IGV parameters updated")
    assert data["preset"] == "sv"
    assert data["response"] == "Parameters updated."

# ─────────────────────────────────────────────────────────────────────────────
# Integration / End-to-End Tests
# These tests exercise the full user journey across all MVP components.
# ─────────────────────────────────────────────────────────────────────────────


def test_integration_end_to_end_file_load_to_chromosomes():
    """E2E: Load BAM file and retrieve chromosome list via API."""
    assert RESOURCE_BAM.exists(), f"Missing test fixture: {RESOURCE_BAM}"

    client = TestClient(main.app)
    t0 = time.monotonic()
    response = client.get("/api/bam/chromosomes", params={"bam_path": str(RESOURCE_BAM)})
    elapsed = time.monotonic() - t0

    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    data = response.json()
    assert "chromosomes" in data
    chroms = data["chromosomes"]
    assert isinstance(chroms, list) and len(chroms) > 0
    for chrom in chroms:
        assert "name" in chrom
        assert "length" in chrom
        assert isinstance(chrom["length"], int) and chrom["length"] > 0
    assert elapsed < 5.0, f"Chromosome API took {elapsed:.2f}s — must be <5s"


def test_integration_end_to_end_bam_region_coverage():
    """E2E: Retrieve region coverage and reads in IGV.js-compatible format."""
    assert RESOURCE_BAM.exists(), f"Missing test fixture: {RESOURCE_BAM}"

    client = TestClient(main.app)
    t0 = time.monotonic()
    response = client.post(
        "/api/region",
        json={"bam_path": str(RESOURCE_BAM), "region": "20:59000-61000", "mode": "path"},
    )
    elapsed = time.monotonic() - t0

    assert response.status_code == 200
    data = response.json()

    # Validate IGV.js-compatible coverage format
    assert "coverage" in data
    assert "reads" in data
    coverage = data["coverage"]
    reads = data["reads"]
    assert isinstance(coverage, list) and len(coverage) > 0
    assert isinstance(reads, list) and len(reads) > 0

    # Every coverage point must have pos and depth (IGV.js contract)
    for point in coverage:
        assert "pos" in point, f"Missing 'pos' in coverage point: {point}"
        assert "depth" in point, f"Missing 'depth' in coverage point: {point}"
        assert isinstance(point["pos"], int)
        assert isinstance(point["depth"], int)

    # Every read must have name, start, end (IGV.js contract)
    for read in reads:
        assert "name" in read
        assert "start" in read
        assert "end" in read
        assert read["end"] >= read["start"]

    assert elapsed < 5.0, f"Region API took {elapsed:.2f}s — must be <5s"


def test_integration_end_to_end_chat_response_schema(monkeypatch):
    """E2E: Full chat pipeline returns a valid ChatResponse with all required fields."""
    assert RESOURCE_BAM.exists(), f"Missing test fixture: {RESOURCE_BAM}"

    monkeypatch.setattr(graph_module, "USE_LLM", False)

    client = TestClient(main.app)
    response = client.post(
        "/api/chat",
        json={
            "message": "show variant evidence",
            "mode": "path",
            "bam_path": str(RESOURCE_BAM),
            "region": "20:59000-61000",
        },
    )

    assert response.status_code == 200
    data = response.json()

    # Validate ChatResponse schema — all required top-level fields
    assert "response" in data, "Missing 'response' field"
    assert "coverage" in data, "Missing 'coverage' field"
    assert "reads" in data, "Missing 'reads' field"
    assert isinstance(data["response"], str) and data["response"] != ""
    assert isinstance(data["coverage"], list)
    assert isinstance(data["reads"], list)

    # variant_assessment must be a dict (may be empty when no SV)
    assert isinstance(data.get("variant_assessment", {}), dict)

    # metrics must be a dict
    assert isinstance(data.get("metrics", {}), dict)

    # sv_evidence must be a list
    assert isinstance(data.get("sv_evidence", []), list)


def test_integration_end_to_end_chat_response_timing(monkeypatch):
    """E2E: Full chat pipeline completes within the 5s performance SLA."""
    assert RESOURCE_BAM.exists(), f"Missing test fixture: {RESOURCE_BAM}"

    monkeypatch.setattr(graph_module, "USE_LLM", False)

    client = TestClient(main.app)
    timings = []

    for _ in range(3):
        t0 = time.monotonic()
        response = client.post(
            "/api/chat",
            json={
                "message": "analyze coverage",
                "mode": "path",
                "bam_path": str(RESOURCE_BAM),
                "region": "20:59000-61000",
            },
        )
        elapsed = time.monotonic() - t0
        timings.append(elapsed)
        assert response.status_code == 200

    max_time = max(timings)
    avg_time = sum(timings) / len(timings)
    # Log timings for observability
    print(f"\n[PERF] Chat response timings (3 runs): {[f'{t:.3f}s' for t in timings]}")
    print(f"[PERF] Max: {max_time:.3f}s, Avg: {avg_time:.3f}s")
    assert max_time < 5.0, f"Max chat response time {max_time:.2f}s exceeds 5s SLA"


def test_integration_end_to_end_agent_pipeline_states(monkeypatch):
    """E2E: LangGraph pipeline transitions through all four agent stages correctly."""
    import app.agents.graph as gm

    monkeypatch.setattr(gm, "USE_LLM", False)

    from app.agents.state import ChatState
    from app.agents.graph import intent_agent, bam_agent, variant_agent, response_agent

    state: ChatState = {
        "message": "analyze structural variant evidence at 20:59000-61000",
        "mode": "path",
        "bam_path": str(RESOURCE_BAM),
        "region": "20:59000-61000",
    }

    # Stage 1 — intent agent sets intent
    state = intent_agent(state)
    assert "intent" in state, "intent_agent must set 'intent' key"
    assert state["intent"] in (
        "view_region", "analyze_coverage", "analyze_reads",
        "analyze_variant", "adjust_igv", "general_question", "unknown"
    ), f"Unexpected intent: {state['intent']}"

    # Stage 2 — BAM agent fetches coverage/reads
    state = bam_agent(state)
    assert "coverage" in state, "bam_agent must populate 'coverage'"
    assert "reads" in state, "bam_agent must populate 'reads'"
    assert isinstance(state["coverage"], list)
    assert isinstance(state["reads"], list)
    assert len(state["coverage"]) > 0, "Expected >0 coverage points from BAM"
    assert len(state["reads"]) > 0, "Expected >0 reads from BAM"

    # Stage 3 — variant agent produces variant assessment
    state = variant_agent(state)
    assert "variant_assessment" in state, "variant_agent must set 'variant_assessment'"
    va = state["variant_assessment"]
    assert "sv_present" in va
    assert "sv_type" in va
    assert "confidence" in va
    assert "evidence" in va
    assert isinstance(va["evidence"], list)
    assert 0.0 <= float(va["confidence"]) <= 1.0

    # Stage 4 — response agent produces a non-empty response
    state = response_agent(state)
    assert "response" in state, "response_agent must set 'response'"
    assert isinstance(state["response"], str) and state["response"] != ""


def test_integration_end_to_end_igv_param_pipeline(monkeypatch):
    """E2E: Setting IGV params via chat message flows through pipeline and returns in response."""
    monkeypatch.setattr(graph_module, "USE_LLM", False)

    client = TestClient(main.app)
    response = client.post(
        "/api/chat",
        json={
            "message": "set trackHeight: 200 and enable view as pairs",
            "mode": "path",
            "bam_path": str(RESOURCE_BAM),
            "region": "20:59000-61000",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data.get("igv_params") is not None, "Expected igv_params in response"
    assert data["igv_params"].get("trackHeight") == 200, "trackHeight not set correctly"
    assert data["igv_params"].get("viewAsPairs") is True, "viewAsPairs not set correctly"
    assert data.get("igv_feedback") is not None
    assert "response" in data and data["response"] != ""


def test_end_to_end_region_api_igv_compatible_format():
    """E2E: /api/region returns data in IGV.js-compatible format with correct field types."""
    assert RESOURCE_BAM.exists(), f"Missing test fixture: {RESOURCE_BAM}"

    client = TestClient(main.app)
    response = client.post(
        "/api/region",
        json={"bam_path": str(RESOURCE_BAM), "region": "20:59000-61000", "mode": "path"},
    )

    assert response.status_code == 200
    data = response.json()

    # IGV.js requires coverage to be an array of {pos, depth}
    coverage = data["coverage"]
    assert all("pos" in c and "depth" in c for c in coverage), "Coverage items missing pos/depth"
    depths = [c["depth"] for c in coverage]
    assert all(isinstance(d, int) and d >= 0 for d in depths), "Depths must be non-negative ints"

    # IGV.js reads need at minimum name, start, end, strand
    reads = data["reads"]
    assert len(reads) > 0, "Expected reads in region 20:59000-61000"
    for read in reads:
        assert isinstance(read["start"], int) and read["start"] > 0
        assert isinstance(read["end"], int) and read["end"] >= read["start"]
        assert read.get("strand") in ("+", "-"), f"Invalid strand: {read.get('strand')}"


# ─────────────────────────────────────────────────────────────────────────────
# T02: Agent-pipeline tests — individual agent correctness and state fidelity
# Each test targets a single stage or a specific query-shape scenario.
# ─────────────────────────────────────────────────────────────────────────────


def test_agent_intent_extracts_region_and_intent(monkeypatch):
    """intent_agent correctly extracts region and intent from a variety of user messages."""
    import app.agents.graph as gm

    monkeypatch.setattr(gm, "USE_LLM", False)

    from app.agents.graph import intent_agent
    from app.agents.state import ChatState

    # Region query: should extract region from message text.
    # Note: avoid "show reads" — "reads" triggers the showReadNames alias in the IGV param extractor.
    state: ChatState = {"message": "view chr1:1000-2000", "mode": "path"}
    result = intent_agent(state)
    assert result.get("intent") in ("view_region", "analyze_coverage", "analyze_reads", "analyze_variant"), \
        f"Unexpected intent: {result.get('intent')}"
    assert result.get("region") == "chr1:1000-2000", \
        f"Expected region 'chr1:1000-2000', got {result.get('region')}"

    # Variant query: VARIANT_KEYWORDS should trigger analyze_variant
    state2: ChatState = {"message": "is there a structural variant?", "mode": "path", "region": "chr1:100-200"}
    result2 = intent_agent(state2)
    assert result2.get("intent") == "analyze_variant", \
        f"Expected 'analyze_variant', got {result2.get('intent')}"
    assert result2.get("region") == "chr1:100-200"

    # IGV param query: trackHeight should map to adjust_igv without needing region
    state3: ChatState = {"message": "set trackHeight: 80", "mode": "path", "region": "chr1:100-200"}
    result3 = intent_agent(state3)
    assert result3.get("intent") == "adjust_igv"
    assert result3.get("igv_params", {}).get("trackHeight") == 80


def test_agent_bam_agent_populates_coverage_and_reads(monkeypatch):
    """bam_agent queries the real BAM and populates both 'coverage' and 'reads' in state."""
    assert RESOURCE_BAM.exists(), f"Missing test fixture: {RESOURCE_BAM}"

    import app.agents.graph as gm

    monkeypatch.setattr(gm, "USE_LLM", False)

    from app.agents.graph import bam_agent
    from app.agents.state import ChatState

    state: ChatState = {
        "message": "show me the reads",
        "mode": "path",
        "intent": "analyze_reads",
        "bam_path": str(RESOURCE_BAM),
        "region": "20:59000-61000",
    }
    result = bam_agent(state)

    # Coverage must be populated with IGV.js-compatible entries
    assert "coverage" in result and isinstance(result["coverage"], list)
    assert len(result["coverage"]) > 0, "bam_agent must return non-empty coverage"
    for point in result["coverage"]:
        assert "pos" in point and "depth" in point, f"Coverage point missing pos/depth: {point}"
        assert isinstance(point["pos"], int) and isinstance(point["depth"], int)

    # Reads must be populated
    assert "reads" in result and isinstance(result["reads"], list)
    assert len(result["reads"]) > 0, "bam_agent must return non-empty reads"
    for read in result["reads"]:
        assert "name" in read
        assert "start" in read and "end" in read

    # State keys from before bam_agent must still be present (no silent drops)
    assert result.get("intent") == "analyze_reads"
    assert result.get("bam_path") == str(RESOURCE_BAM)
    assert result.get("region") == "20:59000-61000"


def test_agent_variant_agent_produces_structured_assessment():
    """variant_agent returns a well-formed variant_assessment dict from synthetic reads."""
    from app.agents.graph import variant_agent
    from app.agents.state import ChatState

    # Craft reads with clear SV signals: high soft-clip + interchromosomal mates
    sv_reads = [
        {
            "name": f"read_{i}",
            "start": 100 + i,
            "end": 170 + i,
            "strand": "+" if i % 2 == 0 else "-",
            "has_soft_clip": True,
            "insertion_bases": 8,
            "deletion_bases": 0,
            "is_paired": True,
            "mate_chromosome": "chr5",   # interchromosomal — strong BND signal
            "pair_orientation": "LR",
            "insert_size": 600,
        }
        for i in range(12)
    ]
    coverage = [{"pos": 100 + i, "depth": 15} for i in range(70)]

    state: ChatState = {
        "message": "is there an SV here?",
        "mode": "path",
        "region": "chr1:100-200",
        "reads": sv_reads,
        "coverage": coverage,
    }
    result = variant_agent(state)

    va = result.get("variant_assessment", {})

    # Required keys
    assert "sv_present" in va, "variant_assessment missing 'sv_present'"
    assert "sv_type" in va, "variant_assessment missing 'sv_type'"
    assert "confidence" in va, "variant_assessment missing 'confidence'"
    assert "evidence" in va, "variant_assessment missing 'evidence'"
    assert "metrics" in va, "variant_assessment missing 'metrics'"
    assert "scores" in va, "variant_assessment missing 'scores'"

    # Confidence is a float in [0, 1]
    assert isinstance(va["confidence"], float), "confidence must be float"
    assert 0.0 <= va["confidence"] <= 1.0, f"confidence out of range: {va['confidence']}"

    # Evidence is a list of non-empty strings
    assert isinstance(va["evidence"], list) and len(va["evidence"]) > 0
    for e in va["evidence"]:
        assert isinstance(e, str) and e != ""

    # With interchromosomal mates, BND score should be elevated
    scores = va.get("scores", {})
    assert scores.get("BND", 0.0) > 0.0, "Expected BND score > 0 with interchromosomal mates"

    # SV should be detected as present with these signals
    assert va["sv_present"] is True, f"Expected sv_present=True, got {va['sv_present']}"

    # Metrics must include read_count
    assert "read_count" in va["metrics"]
    assert va["metrics"]["read_count"] == len(sv_reads)

    # State keys from before variant_agent are preserved
    assert result.get("region") == "chr1:100-200"


def test_agent_response_agent_formats_chatresponse(monkeypatch):
    """response_agent produces a non-empty, structured response for all query shapes."""
    import app.agents.graph as gm

    monkeypatch.setattr(gm, "USE_LLM", False)

    from app.agents.graph import response_agent
    from app.agents.state import ChatState

    coverage = [{"pos": 100 + i, "depth": 20} for i in range(10)]
    reads = [{"name": "r1", "start": 100, "end": 150, "strand": "+", "mapq": 60}]

    # Shape 1 — region query: response summarises the region
    state_region: ChatState = {
        "message": "show me this region",
        "intent": "view_region",
        "region": "chr1:100-200",
        "coverage": coverage,
        "reads": reads,
        "variant_assessment": {},
        "mode": "path",
    }
    result_region = response_agent(state_region)
    assert isinstance(result_region.get("response"), str)
    assert result_region["response"] != "", "response must be non-empty for region query"

    # Shape 2 — variant query: response mentions SV presence
    state_variant: ChatState = {
        "message": "is there a deletion?",
        "intent": "analyze_variant",
        "region": "chr1:100-200",
        "coverage": coverage,
        "reads": reads,
        "variant_assessment": {
            "sv_present": True,
            "sv_type": "DEL",
            "confidence": 0.7,
            "evidence": ["Coverage drop is observed in the inspected region."],
            "metrics": {"read_count": 1},
        },
        "mode": "path",
    }
    result_variant = response_agent(state_variant)
    assert isinstance(result_variant.get("response"), str)
    assert result_variant["response"] != ""
    # Fallback template mentions DEL
    assert "DEL" in result_variant["response"], "Expected variant type in response"

    # Shape 3 — parameter change: pre-set response is preserved, igv_params not cleared
    state_param: ChatState = {
        "message": "set trackHeight: 150",
        "intent": "adjust_igv",
        "region": "chr1:100-200",
        "coverage": [],
        "reads": [],
        "igv_params": {"trackHeight": 150},
        "igv_feedback": "IGV parameters updated: {'trackHeight': 150}",
        "response": "IGV settings updated.",
        "mode": "path",
    }
    result_param = response_agent(state_param)
    # response_agent must not clear a pre-set response
    assert result_param.get("response") is not None and result_param["response"] != ""
    # igv_params must be preserved
    assert result_param.get("igv_params", {}).get("trackHeight") == 150


def test_agent_pipeline_no_intermediate_state_dropped(monkeypatch):
    """Full pipeline (intent→bam→variant→response) never drops state keys set by earlier stages."""
    assert RESOURCE_BAM.exists(), f"Missing test fixture: {RESOURCE_BAM}"

    import app.agents.graph as gm

    monkeypatch.setattr(gm, "USE_LLM", False)

    from app.agents.graph import intent_agent, bam_agent, variant_agent, response_agent
    from app.agents.state import ChatState

    initial: ChatState = {
        "message": "detect deletion at 20:59000-61000",
        "mode": "path",
        "bam_path": str(RESOURCE_BAM),
        "region": "20:59000-61000",
    }

    after_intent = intent_agent(dict(initial))  # type: ignore[arg-type]
    assert "intent" in after_intent, "intent_agent must set 'intent'"
    assert "region" in after_intent, "intent_agent must preserve 'region'"
    assert "bam_path" in after_intent, "intent_agent must preserve 'bam_path'"
    assert "message" in after_intent, "intent_agent must preserve 'message'"

    after_bam = bam_agent(after_intent)
    assert "coverage" in after_bam, "bam_agent must add 'coverage'"
    assert "reads" in after_bam, "bam_agent must add 'reads'"
    # Prior state keys still present
    assert after_bam.get("intent") == after_intent.get("intent"), "bam_agent must not change 'intent'"
    assert after_bam.get("region") == after_intent.get("region"), "bam_agent must not change 'region'"

    after_variant = variant_agent(after_bam)
    assert "variant_assessment" in after_variant, "variant_agent must add 'variant_assessment'"
    # Prior state keys still present
    assert after_variant.get("coverage") == after_bam.get("coverage"), "variant_agent must not drop 'coverage'"
    assert after_variant.get("reads") == after_bam.get("reads"), "variant_agent must not drop 'reads'"
    assert after_variant.get("intent") == after_bam.get("intent"), "variant_agent must not drop 'intent'"

    after_response = response_agent(after_variant)
    assert "response" in after_response and after_response["response"] != ""
    # All prior state keys still present
    assert after_response.get("variant_assessment") is not None, "response_agent must not drop 'variant_assessment'"
    assert after_response.get("coverage") == after_variant.get("coverage"), "response_agent must not drop 'coverage'"
    assert after_response.get("reads") == after_variant.get("reads"), "response_agent must not drop 'reads'"
    assert after_response.get("region") == "20:59000-61000", "response_agent must not drop 'region'"

    # Final state contains all required ChatResponse fields
    for key in ("response", "coverage", "reads", "region", "variant_assessment"):
        assert key in after_response, f"Final state missing required ChatResponse key: '{key}'"


def test_integration_end_to_end_full_user_journey(monkeypatch):
    """E2E: Simulate a complete user workflow — load file, inspect chromosomes, query region, run chat."""
    assert RESOURCE_BAM.exists(), f"Missing test fixture: {RESOURCE_BAM}"
    monkeypatch.setattr(graph_module, "USE_LLM", False)

    client = TestClient(main.app)

    # Step 1: Health check
    health = client.get("/api/health")
    assert health.status_code == 200 and health.json() == {"status": "ok"}

    # Step 2: Load BAM — verify file serving works (range request)
    file_response = client.get(
        "/api/file",
        params={"path": str(RESOURCE_BAM)},
        headers={"Range": "bytes=0-3"},
    )
    assert file_response.status_code == 206
    # BAM magic bytes: 1f 8b (gzip) or 42 41 4d (BAM)
    assert len(file_response.content) > 0

    # Step 3: Get chromosomes
    chroms_response = client.get("/api/bam/chromosomes", params={"bam_path": str(RESOURCE_BAM)})
    assert chroms_response.status_code == 200
    chrom_names = [c["name"] for c in chroms_response.json()["chromosomes"]]
    assert len(chrom_names) > 0

    # Step 4: Query region data (use first available chromosome from header)
    region = "20:59000-61000"  # test.bam is chr20
    region_response = client.post(
        "/api/region",
        json={"bam_path": str(RESOURCE_BAM), "region": region, "mode": "path"},
    )
    assert region_response.status_code == 200
    region_data = region_response.json()
    assert len(region_data["coverage"]) > 0
    assert len(region_data["reads"]) > 0

    # Step 5: Chat analysis — full pipeline with variant assessment
    t0 = time.monotonic()
    chat_response = client.post(
        "/api/chat",
        json={
            "message": "Is there a structural variant in this region?",
            "mode": "path",
            "bam_path": str(RESOURCE_BAM),
            "region": region,
        },
    )
    elapsed = time.monotonic() - t0
    assert chat_response.status_code == 200
    chat_data = chat_response.json()
    # All ChatResponse fields present
    assert "response" in chat_data
    assert "coverage" in chat_data
    assert "reads" in chat_data
    assert "variant_assessment" in chat_data
    assert "metrics" in chat_data
    # Coverage and reads match step 4 data
    assert chat_data["coverage"] == region_data["coverage"]
    assert chat_data["reads"] == region_data["reads"]
    # Performance SLA
    assert elapsed < 5.0, f"Full chat journey took {elapsed:.2f}s — must be <5s"
    print(f"\n[PERF] Full user journey chat elapsed: {elapsed:.3f}s")


# ─────────────────────────────────────────────────────────────────────────────
# T03: Local-only processing tests — confirm no genomic data leaves the system
# R005: BAM/VCF data must never be transmitted to any external API or service.
# Boundaries audited:
#   1. browser → FastAPI   : only message text + metadata (mode, region, bam_path)
#   2. FastAPI → pysam     : local-only file I/O via AlignmentFile("rb")
#   3. FastAPI → LangGraph : only user message text + stats, never raw genomic data
#   4. LangGraph → LLM     : only text/stats; raw BAM bytes/sequences never included
# ─────────────────────────────────────────────────────────────────────────────


def test_local_only_processing(monkeypatch):
    """R005: During a full chat pipeline, no BAM-content bytes leave the process.

    Strategy: intercept every outbound HTTP request made by the httpx/requests layers
    that LangChain-OpenAI uses. Capture request bodies. Assert that none contain
    BAM magic bytes, raw read name patterns, or CIGAR strings that could only come
    from live BAM data.  A side effect of USE_LLM=False is that no HTTP call is made
    at all — that is the strongest possible evidence.

    This test verifies three things:
    1. With USE_LLM=False the pipeline completes successfully with NO outbound requests.
    2. With USE_LLM=False the request body passed to the (stubbed) LLM contains only
       text/stats, never raw genomic sequences or CIGAR strings from the BAM.
    3. The BAM service layer (get_coverage / get_reads) returns aggregated statistics,
       not raw binary genomic content that could be accidentally forwarded.
    """
    assert RESOURCE_BAM.exists(), f"Missing test fixture: {RESOURCE_BAM}"

    # Track all outbound HTTP calls (none should occur in USE_LLM=False path)
    outbound_calls: list = []

    # Patch httpx.Client.send — used by LangChain's OpenAI integration
    original_send = None
    try:
        import httpx
        original_send = httpx.Client.send

        def _spy_send(self, request, *args, **kwargs):
            url = str(request.url)
            # Exclude the TestClient's own ASGI transport calls (host=testserver)
            # — those are the test request itself, not external outbound calls.
            if "testserver" not in url:
                outbound_calls.append({
                    "url": url,
                    "body": request.content,
                })
            return original_send(self, request, *args, **kwargs)

        monkeypatch.setattr(httpx.Client, "send", _spy_send)
    except ImportError:
        pass  # httpx not available; skip the outbound-call assertion

    # Ensure LLM is disabled — no real API calls should happen
    monkeypatch.setattr(graph_module, "USE_LLM", False)

    client = TestClient(main.app)
    response = client.post(
        "/api/chat",
        json={
            "message": "analyze structural variant at 20:59000-61000",
            "mode": "path",
            "bam_path": str(RESOURCE_BAM),
            "region": "20:59000-61000",
        },
    )

    assert response.status_code == 200, f"Chat failed: {response.text}"
    data = response.json()

    # ── Assertion 1: no outbound HTTP calls to external hosts were made ────
    # (TestClient's own calls to http://testserver are excluded from tracking)
    assert len(outbound_calls) == 0, (
        f"Expected 0 external HTTP calls in USE_LLM=False mode, got {len(outbound_calls)}. "
        f"URLs: {[c['url'] for c in outbound_calls]}"
    )

    # ── Assertion 2: coverage / reads returned are aggregated statistics ───
    # Coverage items are {pos: int, depth: int} — no sequences, no raw bytes
    for point in data.get("coverage", []):
        assert set(point.keys()) <= {"pos", "depth"}, (
            f"Coverage point has unexpected keys (possible raw data leak): {set(point.keys())}"
        )
        assert isinstance(point["pos"], int)
        assert isinstance(point["depth"], int)

    # Reads are structured metadata dicts — verify no 'sequence' or 'qual' fields
    BAM_SENSITIVE_FIELDS = {"sequence", "qual", "raw_sequence", "base_qualities", "query_sequence"}
    for read in data.get("reads", []):
        leaked = BAM_SENSITIVE_FIELDS & set(read.keys())
        assert not leaked, (
            f"Read dict contains sensitive genomic fields that should not leave the service: {leaked}"
        )

    # ── Assertion 3: variant_assessment contains only derived metrics ──────
    va = data.get("variant_assessment", {})
    assert "sv_present" in va
    assert "sv_type" in va
    assert "confidence" in va
    assert "evidence" in va
    # Evidence items are human-readable strings, not raw data
    for evidence_item in va.get("evidence", []):
        assert isinstance(evidence_item, str), "evidence items must be strings, not raw data"
        # Evidence must not contain CIGAR-like patterns (sign of raw data leakage)
        assert not re.search(r"\d+[MIDNSHPX=]{1,2}\d+", evidence_item), (
            f"Evidence string looks like a CIGAR string (possible data leakage): {evidence_item!r}"
        )

    print("\n[R005] Local-only processing verified: 0 outbound HTTP calls, "
          "no raw genomic fields in response, all evidence items are human-readable strings.")


def test_no_data_upload(monkeypatch):
    """R005: Confirm that raw BAM content is never embedded in LLM payloads.

    Even when USE_LLM=True, the LLM is only given: user message text, coverage
    statistics (min/max/mean), and read counts — never genomic sequences, CIGAR
    strings, or raw binary data.

    Strategy: patch ChatOpenAI.invoke to capture the messages list, then run the
    full pipeline and inspect every message sent to the stub LLM.
    """
    assert RESOURCE_BAM.exists(), f"Missing test fixture: {RESOURCE_BAM}"

    captured_llm_messages: list = []

    class _CapturingFakeLLM:
        """Fake LLM that records all messages passed to invoke() for inspection."""

        def __init__(self, *args, **kwargs):
            pass

        def invoke(self, messages):
            # Capture all message content for later inspection
            captured_llm_messages.append([
                getattr(m, "content", str(m)) for m in messages
            ])
            # Return a valid JSON stub for the intent agent
            system_content = getattr(messages[0], "content", "") if messages else ""
            if "Respond in JSON format" in system_content:
                return SimpleNamespace(
                    content='{"intent": "analyze_variant", "region": null, "reasoning": "stub"}'
                )
            return SimpleNamespace(content="Stub genomics response.")

    # Force LLM path to be active (patch USE_LLM=True) but intercept at ChatOpenAI
    monkeypatch.setattr(graph_module, "USE_LLM", True)
    monkeypatch.setattr(graph_module, "get_llm_model", lambda: _CapturingFakeLLM())

    client = TestClient(main.app)
    response = client.post(
        "/api/chat",
        json={
            "message": "Is there a deletion at 20:59000-61000?",
            "mode": "path",
            "bam_path": str(RESOURCE_BAM),
            "region": "20:59000-61000",
        },
    )

    assert response.status_code == 200, f"Chat failed: {response.text}"
    assert len(captured_llm_messages) > 0, "Expected at least one LLM invocation in USE_LLM=True mode"

    # BAM magic bytes, CIGAR patterns, and raw sequence characters to reject
    BAM_MAGIC = b"\x1f\x8b"  # gzip/BAM magic
    # Patterns that would only appear if raw genomic data were forwarded
    FORBIDDEN_PATTERNS = [
        # CIGAR string (e.g., "75M", "10S65M", "2I60M3D")
        re.compile(r"\b\d{1,4}[MIDNSHPX=]\b"),
        # Long DNA sequence (>10 consecutive ACGT/N chars)
        re.compile(r"[ACGTN]{10,}", re.IGNORECASE),
    ]

    for invocation_idx, message_contents in enumerate(captured_llm_messages):
        for msg_idx, content in enumerate(message_contents):
            content_str = str(content)
            # Check for BAM magic bytes embedded as text
            assert BAM_MAGIC.decode("latin-1") not in content_str, (
                f"LLM invocation {invocation_idx} msg {msg_idx} contains BAM magic bytes!"
            )
            # Check for raw CIGAR strings or DNA sequences
            for pattern in FORBIDDEN_PATTERNS:
                match = pattern.search(content_str)
                assert match is None, (
                    f"LLM invocation {invocation_idx} msg {msg_idx} contains forbidden pattern "
                    f"{pattern.pattern!r} — possible genomic data leak. "
                    f"Matched: {match.group()!r}"
                )

    # Summarise what was sent to the LLM (for audit trail)
    total_chars = sum(len(content) for inv in captured_llm_messages for content in inv)
    print(
        f"\n[R005] LLM payload audit: {len(captured_llm_messages)} invocations, "
        f"{total_chars} total chars. No raw genomic data detected."
    )
    for idx, inv in enumerate(captured_llm_messages):
        for midx, content in enumerate(inv):
            # Log first 120 chars of each message for the audit trail
            preview = content[:120].replace("\n", "\\n")
            print(f"  invocation[{idx}] msg[{midx}]: {preview!r}")


# ─────────────────────────────────────────────────────────────────────────────
# T04: Requirement-coverage matrix, performance, stress, and boundary tests
#
# REQUIREMENT COVERAGE MATRIX
# ─────────────────────────────────────────────────────────────────────────────
# R001  Users shall load BAM/VCF files and visualize alignments in IGV.js
#       • test_integration_end_to_end_file_load_to_chromosomes
#       • test_smoke_resource_bam_chromosomes_api
#       • test_smoke_resource_file_serving_api
#       • test_r001_file_loading_and_igv_visualization (this file)
#
# R002  Users shall adjust IGV.js presentation via chatbox
#       • test_chat_igv_parameter_adjustment
#       • test_chat_igv_parameter_natural_language
#       • test_chat_igv_presets
#       • test_chat_igv_params_and_feedback
#       • test_integration_end_to_end_igv_param_pipeline
#       • test_r002_igv_parameter_adjustment_via_chat (this file)
#
# R003  System shall provide summary statistics and variant confidence detection
#       • test_agent_variant_agent_produces_structured_assessment
#       • test_integration_end_to_end_chat_response_schema
#       • test_r003_stats_and_confidence_detection (this file)
#
# R004  System shall be agentic using LangGraph framework
#       • test_integration_end_to_end_agent_pipeline_states
#       • test_agent_pipeline_no_intermediate_state_dropped
#       • test_r004_agentic_pipeline_langgraph (this file)
#
# R005  System shall run locally without uploading BAM/VCF data
#       • test_local_only_processing
#       • test_no_data_upload
#       • test_r005_local_only_no_data_leak (this file)
#
# R006  Keep memory footprint minimal
#       • test_r006_memory_footprint_stable (this file)
#
# R007  Maintain fast performance (chat response <5s)
#       • test_integration_end_to_end_chat_response_timing
#       • test_r007_performance_10_sequential_chats (this file)
#       • test_r007_stress_20_rapid_queries (this file)
#
# R008  Keep codebase in sync with progress tracking
#       • test_r008_codebase_sync (this file)
# ─────────────────────────────────────────────────────────────────────────────


# ── R001: File loading and IGV.js visualization ────────────────────────────

def test_r001_file_loading_and_igv_visualization():
    """R001: BAM file is loadable and IGV.js-compatible data is returned via API."""
    assert RESOURCE_BAM.exists(), f"R001: Missing test BAM fixture: {RESOURCE_BAM}"

    client = TestClient(main.app)

    # Byte-range serving of BAM (used by IGV.js to fetch indexed genomic data)
    range_resp = client.get(
        "/api/file",
        params={"path": str(RESOURCE_BAM)},
        headers={"Range": "bytes=0-27"},
    )
    assert range_resp.status_code == 206, "R001: Byte-range serving must return 206"
    assert int(range_resp.headers["content-length"]) == 28

    # Chromosomes endpoint — IGV.js needs this to build the reference menu
    chroms_resp = client.get("/api/bam/chromosomes", params={"bam_path": str(RESOURCE_BAM)})
    assert chroms_resp.status_code == 200, "R001: Chromosome list must be available"
    chromosomes = chroms_resp.json()["chromosomes"]
    assert len(chromosomes) > 0, "R001: BAM must expose at least one chromosome"

    # Region data — IGV.js renders coverage + read tracks from this endpoint
    region_resp = client.post(
        "/api/region",
        json={"bam_path": str(RESOURCE_BAM), "region": "20:59000-61000", "mode": "path"},
    )
    assert region_resp.status_code == 200, "R001: Region data must be accessible"
    region_data = region_resp.json()
    assert len(region_data["coverage"]) > 0, "R001: Coverage data required for IGV.js track"
    assert len(region_data["reads"]) > 0, "R001: Read data required for IGV.js track"

    print(f"\n[R001] ✓ File loading: {len(chromosomes)} chromosomes, "
          f"{len(region_data['coverage'])} coverage points, "
          f"{len(region_data['reads'])} reads returned")


# ── R002: IGV parameter adjustment via chat ────────────────────────────────

def test_r002_igv_parameter_adjustment_via_chat(monkeypatch):
    """R002: Chat interface can adjust multiple IGV.js parameters in one request."""
    monkeypatch.setattr(graph_module, "USE_LLM", False)

    client = TestClient(main.app)

    # Numeric parameter
    resp1 = client.post("/api/chat", json={
        "message": "set trackHeight: 180",
        "mode": "path",
        "bam_path": str(RESOURCE_BAM),
        "region": "20:59000-61000",
    })
    assert resp1.status_code == 200
    assert resp1.json().get("igv_params", {}).get("trackHeight") == 180, "R002: trackHeight"

    # Boolean flag
    resp2 = client.post("/api/chat", json={
        "message": "enable view as pairs",
        "mode": "path",
        "bam_path": str(RESOURCE_BAM),
        "region": "20:59000-61000",
    })
    assert resp2.status_code == 200
    assert resp2.json().get("igv_params", {}).get("viewAsPairs") is True, "R002: viewAsPairs"

    # Named preset
    resp3 = client.post("/api/chat", json={
        "message": "switch to sv preset",
        "mode": "path",
        "bam_path": str(RESOURCE_BAM),
        "region": "20:59000-61000",
    })
    assert resp3.status_code == 200
    assert resp3.json().get("igv_params") is not None, "R002: preset must produce igv_params"

    print("\n[R002] ✓ IGV param adjustment: numeric, boolean, and preset all produce igv_params")


# ── R003: Summary statistics and variant confidence detection ──────────────

def test_r003_stats_and_confidence_detection(monkeypatch):
    """R003: variant_agent produces confidence scores and coverage statistics."""
    from app.agents.graph import variant_agent
    from app.agents.state import ChatState
    from app.services.bam import summarize_coverage

    # Minimal synthetic signal — mix of normal and elevated reads
    reads = [
        {
            "name": f"r{i}", "start": 1000 + i, "end": 1075 + i, "strand": "+",
            "has_soft_clip": i % 3 == 0, "insertion_bases": 0, "deletion_bases": 0,
            "is_paired": True, "mate_chromosome": "20", "pair_orientation": "LR",
            "insert_size": 300,
        }
        for i in range(20)
    ]
    coverage = [{"pos": 1000 + i, "depth": 40 - (i * 2) if i < 15 else 5} for i in range(30)]

    state: ChatState = {
        "message": "what are the coverage statistics?",
        "mode": "path",
        "region": "20:1000-1030",
        "reads": reads,
        "coverage": coverage,
    }
    result = variant_agent(state)
    va = result["variant_assessment"]

    # Confidence is in [0, 1]
    assert 0.0 <= va["confidence"] <= 1.0, f"R003: confidence out of range: {va['confidence']}"
    # Metrics include read_count, soft_clip_fraction, and insert_size_mean
    m = va.get("metrics", {})
    assert "read_count" in m, "R003: metrics must include read_count"
    assert m["read_count"] == len(reads)

    # summarize_coverage produces min/max/mean
    summary = summarize_coverage(coverage)
    assert "min" in summary and "max" in summary and "mean" in summary
    assert summary["min"] <= summary["mean"] <= summary["max"]
    assert summary["min"] >= 0

    print(f"\n[R003] ✓ Stats: confidence={va['confidence']:.3f}, "
          f"read_count={m['read_count']}, coverage_summary={summary}")


# ── R004: Agentic LangGraph pipeline ──────────────────────────────────────

def test_r004_agentic_pipeline_langgraph(monkeypatch):
    """R004: LangGraph multi-agent pipeline executes all four stages end-to-end."""
    assert RESOURCE_BAM.exists(), f"R004: Missing test BAM fixture: {RESOURCE_BAM}"

    monkeypatch.setattr(graph_module, "USE_LLM", False)

    # Validate the compiled graph object is a real LangGraph runnable
    assert hasattr(main, "_graph"), "R004: app.main must expose _graph"
    graph = main._graph
    assert callable(getattr(graph, "invoke", None)), "R004: _graph must have an invoke() method"

    client = TestClient(main.app)
    resp = client.post("/api/chat", json={
        "message": "detect structural variant evidence",
        "mode": "path",
        "bam_path": str(RESOURCE_BAM),
        "region": "20:59000-61000",
    })
    assert resp.status_code == 200, f"R004: Pipeline failed: {resp.text}"
    data = resp.json()

    # All four pipeline outputs must be present
    assert "response" in data, "R004: response_agent stage missing"
    assert "variant_assessment" in data, "R004: variant_agent stage missing"
    assert "coverage" in data, "R004: bam_agent stage missing"
    assert "reads" in data, "R004: bam_agent stage missing"

    print(f"\n[R004] ✓ LangGraph agentic pipeline: "
          f"intent→bam→variant→response all completed successfully")


# ── R005: Local-only processing (explicit requirement test) ───────────────

def test_r005_local_only_no_data_leak(monkeypatch):
    """R005: No BAM/VCF data is transmitted externally (complementary to test_local_only_processing)."""
    assert RESOURCE_BAM.exists(), f"R005: Missing test BAM fixture: {RESOURCE_BAM}"

    monkeypatch.setattr(graph_module, "USE_LLM", False)

    from app.services.bam import get_reads

    # The reads returned by get_reads must not contain raw sequence/quality data
    reads = get_reads(str(RESOURCE_BAM), "20:59000-61000")
    assert len(reads) > 0, "R005: Expected non-empty reads list"

    SENSITIVE_KEYS = {"sequence", "qual", "query_sequence", "base_qualities", "raw_sequence"}
    for read in reads:
        leaked_keys = SENSITIVE_KEYS & set(read.keys())
        assert not leaked_keys, (
            f"R005: get_reads() returned sensitive genomic field(s): {leaked_keys} — "
            f"these must never be exposed via the API"
        )

    # The BAM file itself is never returned — only metadata/stats are serialised
    # Verify the /api/region response contains no raw sequences
    client = TestClient(main.app)
    region_resp = client.post("/api/region", json={
        "bam_path": str(RESOURCE_BAM), "region": "20:59000-61000", "mode": "path"
    })
    assert region_resp.status_code == 200
    region_reads = region_resp.json().get("reads", [])
    for r in region_reads:
        assert SENSITIVE_KEYS.isdisjoint(set(r.keys())), (
            f"R005: /api/region returned sensitive key(s): {SENSITIVE_KEYS & set(r.keys())}"
        )

    print(f"\n[R005] ✓ Local-only: {len(reads)} reads returned, "
          f"no sensitive genomic fields in any read dict")


# ── R006: Memory footprint ─────────────────────────────────────────────────

def test_r006_memory_footprint_stable(monkeypatch):
    """R006: Memory usage does not grow unbounded across multiple sequential chat requests.

    Uses tracemalloc (stdlib) to measure Python heap allocations.  A hard 50 MB
    growth cap is applied — generous enough to avoid false positives yet tight
    enough to catch a reference-retaining bug.
    """
    assert RESOURCE_BAM.exists(), f"R006: Missing test BAM fixture: {RESOURCE_BAM}"

    monkeypatch.setattr(graph_module, "USE_LLM", False)

    client = TestClient(main.app)
    payload = {
        "message": "analyze structural variant",
        "mode": "path",
        "bam_path": str(RESOURCE_BAM),
        "region": "20:59000-61000",
    }

    # Warm-up: run one request so Python import/JIT costs don't count
    client.post("/api/chat", json=payload)

    tracemalloc.start()
    snapshot_before = tracemalloc.take_snapshot()

    N = 10
    for _ in range(N):
        r = client.post("/api/chat", json=payload)
        assert r.status_code == 200

    snapshot_after = tracemalloc.take_snapshot()
    tracemalloc.stop()

    # Compare memory statistics
    stats = snapshot_after.compare_to(snapshot_before, "lineno")
    total_growth_bytes = sum(s.size_diff for s in stats if s.size_diff > 0)
    total_growth_mb = total_growth_bytes / (1024 * 1024)

    print(f"\n[R006] Memory growth across {N} requests: {total_growth_mb:.2f} MB")
    # Top allocators for observability
    top = sorted(stats, key=lambda s: s.size_diff, reverse=True)[:5]
    for stat in top:
        if stat.size_diff > 0:
            print(f"  +{stat.size_diff / 1024:.1f} KB  {stat.traceback}")

    assert total_growth_mb < 50, (
        f"R006: Memory grew {total_growth_mb:.1f} MB over {N} requests — "
        f"possible memory leak (threshold: 50 MB)"
    )


# ── R007: Performance — 10 sequential chats all <5s ───────────────────────

def test_r007_performance_10_sequential_chats(monkeypatch):
    """R007: Ten sequential chat requests must ALL complete within the 5s SLA.

    Produces a structured timing baseline suitable for future regression detection.
    """
    assert RESOURCE_BAM.exists(), f"R007: Missing test BAM fixture: {RESOURCE_BAM}"

    monkeypatch.setattr(graph_module, "USE_LLM", False)

    client = TestClient(main.app)
    timings = []
    responses_ok = 0

    messages = [
        "analyze structural variant",
        "show coverage depth",
        "detect deletion evidence",
        "what is the read depth here?",
        "any split reads indicating SV?",
        "compare insert sizes",
        "show discordant pairs",
        "check soft-clip patterns",
        "is there a translocation?",
        "summarize variant evidence",
    ]

    for msg in messages:
        t0 = time.monotonic()
        resp = client.post("/api/chat", json={
            "message": msg,
            "mode": "path",
            "bam_path": str(RESOURCE_BAM),
            "region": "20:59000-61000",
        })
        elapsed = time.monotonic() - t0
        timings.append(elapsed)
        if resp.status_code == 200:
            responses_ok += 1

    min_t = min(timings)
    max_t = max(timings)
    avg_t = sum(timings) / len(timings)
    p95 = sorted(timings)[int(len(timings) * 0.95)]  # ~95th percentile for 10 samples

    print(f"\n[R007-PERF] 10 sequential chats — "
          f"min={min_t:.3f}s  avg={avg_t:.3f}s  max={max_t:.3f}s  p95={p95:.3f}s")
    print(f"[R007-PERF] Individual timings: {[f'{t:.3f}s' for t in timings]}")
    print(f"[R007-PERF] Successful responses: {responses_ok}/10")

    assert responses_ok == 10, f"R007: Expected all 10 responses OK, got {responses_ok}"
    assert max_t < 5.0, (
        f"R007: Slowest chat response was {max_t:.2f}s — exceeds 5s SLA. "
        f"All timings: {[f'{t:.3f}s' for t in timings]}"
    )


# ── R007: Stress test — 20 rapid-fire queries, no dropped/corrupted responses ─

def test_r007_stress_20_rapid_queries(monkeypatch):
    """R007: 20 rapid sequential queries produce 20 valid, non-corrupted responses.

    Verifies the FastAPI/LangGraph stack does not drop, mix up, or corrupt
    responses under rapid sequential load.  Each response is fully validated
    against the ChatResponse schema.
    """
    assert RESOURCE_BAM.exists(), f"R007-stress: Missing test BAM fixture: {RESOURCE_BAM}"

    monkeypatch.setattr(graph_module, "USE_LLM", False)

    client = TestClient(main.app)
    N = 20
    results = []
    timings = []

    for i in range(N):
        t0 = time.monotonic()
        resp = client.post("/api/chat", json={
            "message": f"analyze variant evidence query {i}",
            "mode": "path",
            "bam_path": str(RESOURCE_BAM),
            "region": "20:59000-61000",
        })
        elapsed = time.monotonic() - t0
        timings.append(elapsed)
        results.append((resp.status_code, resp.json() if resp.status_code == 200 else None))

    # All 20 must return 200
    failed = [(i, code) for i, (code, _) in enumerate(results) if code != 200]
    assert not failed, f"R007-stress: {len(failed)} requests failed: {failed}"

    # All 20 responses must be structurally valid (no corruption)
    for i, (_, data) in enumerate(results):
        assert data is not None, f"R007-stress: query {i} returned no JSON"
        assert isinstance(data.get("response"), str) and data["response"] != "", \
            f"R007-stress: query {i} has empty/missing 'response'"
        assert isinstance(data.get("coverage"), list), \
            f"R007-stress: query {i} has non-list 'coverage'"
        assert isinstance(data.get("reads"), list), \
            f"R007-stress: query {i} has non-list 'reads'"
        assert isinstance(data.get("variant_assessment"), dict), \
            f"R007-stress: query {i} has non-dict 'variant_assessment'"

    avg_t = sum(timings) / len(timings)
    max_t = max(timings)
    print(f"\n[R007-STRESS] 20 rapid queries — avg={avg_t:.3f}s  max={max_t:.3f}s")
    print(f"[R007-STRESS] All 20 responses valid. 0 dropped. 0 corrupted.")


# ── Boundary tests — invalid inputs must not crash the server ─────────────

def test_boundary_invalid_region_format():
    """Boundary: malformed region string is rejected with a 4xx error, no crash."""
    client = TestClient(main.app)
    malformed_regions = [
        "chr1-1000-2000",      # wrong separator
        "chr1:",               # missing coords
        "chr1:abc-def",        # non-numeric coords
        "",                    # empty string
        "1000000000:1-2",      # absurd contig name (numeric only)
    ]
    for region in malformed_regions:
        resp = client.post("/api/region", json={
            "bam_path": str(RESOURCE_BAM),
            "region": region,
            "mode": "path",
        })
        assert resp.status_code in (400, 422, 500), (
            f"Expected error status for malformed region {region!r}, got {resp.status_code}"
        )
        # Server must not crash — it must return a JSON body
        assert resp.headers.get("content-type", "").startswith("application/json"), (
            f"Expected JSON error body for malformed region {region!r}"
        )

    print("\n[BOUNDARY] ✓ Malformed region strings all returned error codes (no crashes)")


def test_boundary_nonexistent_bam_path():
    """Boundary: non-existent BAM path returns a 4xx/5xx error, no server crash."""
    client = TestClient(main.app)

    for endpoint, json_body in [
        ("/api/bam/chromosomes", None),
        ("/api/region", {"bam_path": "/nonexistent/path/file.bam",
                          "region": "chr1:1-100", "mode": "path"}),
    ]:
        if json_body is None:
            resp = client.get(endpoint, params={"bam_path": "/nonexistent/path/file.bam"})
        else:
            resp = client.post(endpoint, json=json_body)

        assert resp.status_code in (400, 404, 422, 500), (
            f"Expected error status for nonexistent BAM at {endpoint}, got {resp.status_code}"
        )

    print("\n[BOUNDARY] ✓ Non-existent BAM path handled gracefully (no crash)")


def test_boundary_path_traversal_rejected():
    """Boundary: path traversal attempts in bam_path or region are handled safely."""
    client = TestClient(main.app)

    traversal_paths = [
        "../../etc/passwd",
        "/etc/shadow",
        "../../../root/.ssh/id_rsa",
    ]
    for path in traversal_paths:
        resp = client.get("/api/bam/chromosomes", params={"bam_path": path})
        # Must not succeed — must return an error code
        assert resp.status_code in (400, 403, 404, 422, 500), (
            f"Expected error for path traversal attempt {path!r}, got {resp.status_code}"
        )

    print("\n[BOUNDARY] ✓ Path traversal attempts all rejected safely")


def test_boundary_empty_chat_message(monkeypatch):
    """Boundary: empty or whitespace-only chat message is handled without crash."""
    monkeypatch.setattr(graph_module, "USE_LLM", False)

    client = TestClient(main.app)
    for msg in ["", "   ", "\n"]:
        resp = client.post("/api/chat", json={
            "message": msg,
            "mode": "path",
            "bam_path": str(RESOURCE_BAM),
            "region": "20:59000-61000",
        })
        # May be 200 or 400/422 — but must not be 500 (server crash)
        assert resp.status_code != 500, (
            f"Server must not crash on empty message {msg!r}, got 500: {resp.text}"
        )

    print("\n[BOUNDARY] ✓ Empty/whitespace chat messages handled without 500 error")


def test_boundary_oversized_region(monkeypatch):
    """Boundary: very large region window is handled safely (capped, not crashed)."""
    assert RESOURCE_BAM.exists(), f"Missing test BAM fixture: {RESOURCE_BAM}"

    monkeypatch.setattr(graph_module, "USE_LLM", False)

    client = TestClient(main.app)
    # Request a 100 Mb region — bam.py caps at MAX_REGION_LEN=2000 positions
    resp = client.post("/api/region", json={
        "bam_path": str(RESOURCE_BAM),
        "region": "20:1-100000000",
        "mode": "path",
    })
    # Should succeed (with sampled data) or return a controlled error — not crash
    assert resp.status_code in (200, 400, 404, 422, 500), (
        f"Unexpected status for oversized region: {resp.status_code}"
    )
    if resp.status_code == 200:
        data = resp.json()
        coverage = data.get("coverage", [])
        # MAX_REGION_LEN cap means at most 2000 points even for 100M region
        assert len(coverage) <= 2000, (
            f"Coverage exceeded MAX_REGION_LEN: {len(coverage)} > 2000"
        )
        print(f"\n[BOUNDARY] ✓ Oversized region capped to {len(coverage)} coverage points")
    else:
        print(f"\n[BOUNDARY] ✓ Oversized region returned controlled error {resp.status_code}")


# ── R008: Codebase sync ────────────────────────────────────────────────────

def test_r008_codebase_sync():
    """R008: Core application modules exist and are importable — codebase is coherent."""
    import importlib

    required_modules = [
        "app.main",
        "app.agents.graph",
        "app.agents.state",
        "app.services.bam",
    ]
    for module_name in required_modules:
        try:
            mod = importlib.import_module(module_name)
            assert mod is not None, f"R008: Module {module_name} imported as None"
        except ImportError as exc:
            raise AssertionError(
                f"R008: Required module {module_name!r} is not importable: {exc}"
            ) from exc

    # Verify key public symbols are present
    from app.main import app as fastapi_app, _graph
    from app.agents.graph import intent_agent, bam_agent, variant_agent, response_agent
    from app.agents.state import ChatState
    from app.services.bam import get_coverage, get_reads, summarize_coverage, parse_region

    assert fastapi_app is not None, "R008: FastAPI app must be exportable from app.main"
    assert _graph is not None, "R008: _graph must be compiled and available"
    assert callable(intent_agent), "R008: intent_agent must be callable"
    assert callable(bam_agent), "R008: bam_agent must be callable"
    assert callable(variant_agent), "R008: variant_agent must be callable"
    assert callable(response_agent), "R008: response_agent must be callable"


# ── S02: USE_LLM=True path coverage ──────────────────────────────────────────
# IMPORTANT: intent_agent has an early-return guard — if the message matches a
# known IGV param pattern or preset keyword (via regex), the function returns
# before reaching the LLM.  Tests that want to exercise the LLM branch must use
# messages that do NOT trigger the pattern-matcher.  E.g. "what is the coverage
# here?" reaches the LLM; "set track height to 200" is handled by regex first.

def test_intent_agent_llm_igv_params_extracted(monkeypatch):
    """LLM returns igv_params dict → state has igv_params and igv_feedback set.

    Message "what is the depth here?" does not match any IGV param regex so
    the early-return guard does not fire and the LLM branch is reached.
    """
    import app.agents.graph as gm

    class _FakeLLMParams:
        def __init__(self, *args, **kwargs):
            pass
        def invoke(self, messages):
            return SimpleNamespace(
                content='{"intent": "adjust_igv", "region": null, "igv_params": {"trackHeight": 200}, "preset": null, "reasoning": "test"}'
            )

    monkeypatch.setattr(gm, "get_llm_model", lambda: _FakeLLMParams())
    monkeypatch.setattr(gm, "USE_LLM", True)

    state = {
        "message": "what is the depth here?",   # neutral — no param/preset keyword
        "region": "20:59000-61000",
        "bam_path": "",
        "intent": "",
        "response": "",
    }
    result = gm.intent_agent(state)
    assert result.get("igv_params", {}).get("trackHeight") == 200, (
        f"Expected igv_params['trackHeight']==200, got: {result.get('igv_params')}"
    )
    assert result.get("igv_feedback"), "Expected igv_feedback to be set"
    print("\n[S02] ✓ test_intent_agent_llm_igv_params_extracted passed")


def test_intent_agent_llm_builtin_preset_applied(monkeypatch):
    """LLM returns preset='sv' (empty igv_params) → BUILTIN_PRESETS['sv'] applied to state.

    Message must avoid triggering the non-LLM 'sv' keyword preset check which
    fires when 'sv' appears literally in the message.  Using a neutral message
    keeps the early-return guard quiet so the LLM handles the intent.
    """
    import app.agents.graph as gm

    class _FakeLLMPreset:
        def __init__(self, *args, **kwargs):
            pass
        def invoke(self, messages):
            return SimpleNamespace(
                content='{"intent": "adjust_igv", "region": null, "igv_params": {}, "preset": "sv", "reasoning": "sv preset"}'
            )

    monkeypatch.setattr(gm, "get_llm_model", lambda: _FakeLLMPreset())
    monkeypatch.setattr(gm, "USE_LLM", True)

    state = {
        "message": "optimize display for structural variants",   # no bare 'sv' keyword
        "region": "20:59000-61000",
        "bam_path": "",
        "intent": "",
        "response": "",
    }
    result = gm.intent_agent(state)
    # BUILTIN_PRESETS['sv'] has trackHeight=120
    assert result.get("igv_params", {}).get("trackHeight") == 120, (
        f"Expected igv_params['trackHeight']==120 from sv preset, got: {result.get('igv_params')}"
    )
    assert result.get("igv_feedback"), "Expected igv_feedback to be set"
    print("\n[S02] ✓ test_intent_agent_llm_builtin_preset_applied passed")


def test_intent_agent_llm_user_preset_applied(monkeypatch):
    """LLM returns preset='my_sv' with user_presets in state → user preset applied.

    The message must not contain 'sv' or any other BUILTIN_PRESETS key to avoid
    the early-return guard.  'custom_layout' is a safe neutral phrase.
    """
    import app.agents.graph as gm

    class _FakeLLMUserPreset:
        def __init__(self, *args, **kwargs):
            pass
        def invoke(self, messages):
            return SimpleNamespace(
                content='{"intent": "adjust_igv", "region": null, "igv_params": {}, "preset": "my_sv", "reasoning": "user preset"}'
            )

    monkeypatch.setattr(gm, "get_llm_model", lambda: _FakeLLMUserPreset())
    monkeypatch.setattr(gm, "USE_LLM", True)

    state = {
        "message": "use my custom layout please",   # no BUILTIN_PRESETS key in message
        "region": "20:59000-61000",
        "bam_path": "",
        "intent": "",
        "response": "",
        "user_presets": {"my_sv": {"trackHeight": 300}},
    }
    result = gm.intent_agent(state)
    assert result.get("igv_params", {}).get("trackHeight") == 300, (
        f"Expected igv_params['trackHeight']==300 from user preset my_sv, got: {result.get('igv_params')}"
    )
    assert "my_sv" in result.get("igv_feedback", ""), (
        f"Expected igv_feedback to mention 'my_sv', got: {result.get('igv_feedback')}"
    )
    print("\n[S02] ✓ test_intent_agent_llm_user_preset_applied passed")


def test_intent_agent_llm_unknown_preset_feedback(monkeypatch):
    """LLM returns preset='nosuchpreset' → igv_feedback contains 'not recognized'.

    Neutral message avoids early-return guard.
    """
    import app.agents.graph as gm

    class _FakeLLMUnknownPreset:
        def __init__(self, *args, **kwargs):
            pass
        def invoke(self, messages):
            return SimpleNamespace(
                content='{"intent": "adjust_igv", "region": null, "igv_params": {}, "preset": "nosuchpreset", "reasoning": "unknown"}'
            )

    monkeypatch.setattr(gm, "get_llm_model", lambda: _FakeLLMUnknownPreset())
    monkeypatch.setattr(gm, "USE_LLM", True)

    state = {
        "message": "what can I do with this region?",   # neutral — no param/preset keyword
        "region": "20:59000-61000",
        "bam_path": "",
        "intent": "",
        "response": "",
    }
    result = gm.intent_agent(state)
    feedback = result.get("igv_feedback", "")
    assert "not recognized" in feedback.lower(), (
        f"Expected 'not recognized' in igv_feedback, got: {feedback!r}"
    )
    print("\n[S02] ✓ test_intent_agent_llm_unknown_preset_feedback passed")


def test_intent_agent_llm_exception_fallback(monkeypatch):
    """LLM raises ValueError → fallback uses region + variant keyword → analyze_variant intent.

    Message must NOT trigger the early-return guard, but must contain a VARIANT_KEYWORDS
    match so the fallback branch chooses 'analyze_variant'.  'deletion variant' satisfies
    VARIANT_KEYWORDS without matching any IGV param pattern.
    """
    import app.agents.graph as gm

    class _FakeLLMRaises:
        def __init__(self, *args, **kwargs):
            pass
        def invoke(self, messages):
            raise ValueError("boom")

    monkeypatch.setattr(gm, "get_llm_model", lambda: _FakeLLMRaises())
    monkeypatch.setattr(gm, "USE_LLM", True)

    state = {
        "message": "is there deletion variant evidence here?",   # VARIANT_KEYWORDS match, no param match
        "region": "20:59000-61000",
        "bam_path": "",
        "intent": "",
        "response": "",
    }
    result = gm.intent_agent(state)
    assert result.get("intent") == "analyze_variant", (
        f"Expected intent='analyze_variant' from fallback, got: {result.get('intent')}"
    )
    assert result.get("region") == "20:59000-61000", (
        f"Expected region preserved in fallback, got: {result.get('region')}"
    )
    print("\n[S02] ✓ test_intent_agent_llm_exception_fallback passed")


def test_response_agent_llm_path(monkeypatch):
    """response_agent with USE_LLM=True: fake LLM returns text → state['response'] set.

    Coverage data must use the expected dict format: [{"depth": N, "pos": N}].
    """
    import app.agents.graph as gm

    class _FakeLLMResponse:
        def __init__(self, *args, **kwargs):
            pass
        def invoke(self, messages):
            return SimpleNamespace(content="Test LLM response from response_agent.")

    monkeypatch.setattr(gm, "get_llm_model", lambda: _FakeLLMResponse())
    monkeypatch.setattr(gm, "USE_LLM", True)

    state = {
        "message": "what does this coverage mean?",
        "intent": "analyze_coverage",
        "region": "20:59000-61000",
        "coverage": [{"pos": 59000, "depth": 10}, {"pos": 59001, "depth": 20}],
        "reads": [],
        "response": "",
        "halt": False,
    }
    result = gm.response_agent(state)
    assert result.get("response") == "Test LLM response from response_agent.", (
        f"Expected LLM response text, got: {result.get('response')!r}"
    )
    print("\n[S02] ✓ test_response_agent_llm_path passed")


def test_response_agent_llm_exception_fallback(monkeypatch):
    """response_agent LLM raises exception → non-empty fallback response set.

    Coverage data uses expected dict format.
    """
    import app.agents.graph as gm

    class _FakeLLMResponseRaises:
        def __init__(self, *args, **kwargs):
            pass
        def invoke(self, messages):
            raise RuntimeError("LLM unavailable")

    monkeypatch.setattr(gm, "get_llm_model", lambda: _FakeLLMResponseRaises())
    monkeypatch.setattr(gm, "USE_LLM", True)

    state = {
        "message": "summarize this region",
        "intent": "analyze_coverage",
        "region": "20:59000-61000",
        "coverage": [{"pos": 59000, "depth": 5}, {"pos": 59001, "depth": 10}],
        "reads": [],
        "response": "",
        "halt": False,
    }
    result = gm.response_agent(state)
    fallback = result.get("response", "")
    assert fallback, "Expected non-empty fallback response when LLM raises"
    print("\n[S02] ✓ test_response_agent_llm_exception_fallback passed")


def test_intent_agent_llm_region_extracted_from_llm(monkeypatch):
    """LLM returns a non-null region → state['region'] is set from LLM response (line 252)."""
    import app.agents.graph as gm

    class _FakeLLMRegion:
        def __init__(self, *args, **kwargs):
            pass
        def invoke(self, messages):
            return SimpleNamespace(
                content='{"intent": "view_region", "region": "chr1:100-200", "igv_params": {}, "preset": null, "reasoning": "region test"}'
            )

    monkeypatch.setattr(gm, "get_llm_model", lambda: _FakeLLMRegion())
    monkeypatch.setattr(gm, "USE_LLM", True)

    state = {
        "message": "take me to this location",   # neutral, no param/preset keyword
        "region": None,                          # no region in state — LLM must supply it
        "bam_path": "",
        "intent": "",
        "response": "",
    }
    result = gm.intent_agent(state)
    assert result.get("region") == "chr1:100-200", (
        f"Expected region extracted from LLM response, got: {result.get('region')}"
    )
    assert result.get("intent") == "view_region", (
        f"Expected intent='view_region', got: {result.get('intent')}"
    )
    print("\n[S02] ✓ test_intent_agent_llm_region_extracted_from_llm passed")


def test_intent_agent_llm_exception_fallback_no_region(monkeypatch):
    """LLM raises, no region in state → intent falls back to 'unknown' (lines 288-290)."""
    import app.agents.graph as gm

    class _FakeLLMRaisesNoRegion:
        def __init__(self, *args, **kwargs):
            pass
        def invoke(self, messages):
            raise ValueError("no region fallback")

    monkeypatch.setattr(gm, "get_llm_model", lambda: _FakeLLMRaisesNoRegion())
    monkeypatch.setattr(gm, "USE_LLM", True)

    state = {
        "message": "what does this look like?",   # neutral, no variant keyword, no region
        "region": None,
        "bam_path": "",
        "intent": "",
        "response": "",
    }
    result = gm.intent_agent(state)
    assert result.get("intent") == "unknown", (
        f"Expected intent='unknown' when LLM raises with no region, got: {result.get('intent')}"
    )
    print("\n[S02] ✓ test_intent_agent_llm_exception_fallback_no_region passed")


# ── S02/T03: Clarification-path and user-preset round-trip tests ─────────────


def test_intent_agent_clarification_response(monkeypatch):
    """Ambiguous message with no region and no IGV param hit → halt=True with helpful response."""
    import app.agents.graph as gm

    monkeypatch.setattr(gm, "USE_LLM", False)

    state = {
        "message": "xyzzy blorp",   # gibberish — matches no param alias, no preset, no region
        "region": None,
        "bam_path": "",
        "intent": "",
        "igv_params": {},
        "user_presets": {},
        "response": "",
    }
    result = gm.intent_agent(state)
    assert result.get("halt") is True, (
        f"Expected halt=True for unrecognised message, got halt={result.get('halt')!r}"
    )
    assert result.get("response"), (
        "Expected a non-empty clarification response when halt=True"
    )
    print("\n[S02/T03] ✓ test_intent_agent_clarification_response passed")


def test_intent_agent_clarification_no_crash_empty_message(monkeypatch):
    """Empty message with no region → no exception raised, response non-empty or halt=True."""
    import app.agents.graph as gm

    monkeypatch.setattr(gm, "USE_LLM", False)

    state = {
        "message": "",
        "region": None,
        "bam_path": "",
        "intent": "",
        "igv_params": {},
        "user_presets": {},
        "response": "",
    }
    # Must not raise
    result = gm.intent_agent(state)
    has_response = bool(result.get("response"))
    is_halted = result.get("halt") is True
    assert has_response or is_halted, (
        "Expected non-empty response or halt=True for empty message"
    )
    print("\n[S02/T03] ✓ test_intent_agent_clarification_no_crash_empty_message passed")


def test_intent_agent_user_preset_via_state(monkeypatch):
    """User-defined preset passed via state['preset'] is applied by intent_agent."""
    import app.agents.graph as gm

    monkeypatch.setattr(gm, "USE_LLM", False)

    # 'focus' is not a BUILTIN_PRESETS key; must pass preset via state["preset"]
    # so the code's `if "preset" in state: preset = state["preset"]` branch fires.
    state = {
        "message": "apply focus preset",
        "preset": "focus",                           # explicit preset key in state
        "region": None,
        "bam_path": "",
        "intent": "",
        "igv_params": {},
        "user_presets": {"focus": {"trackHeight": 250, "showCenterGuide": True}},
        "response": "",
    }
    result = gm.intent_agent(state)
    assert result.get("intent") == "adjust_igv", (
        f"Expected intent='adjust_igv', got: {result.get('intent')!r}"
    )
    assert result.get("igv_params", {}).get("trackHeight") == 250, (
        f"Expected trackHeight=250 from user preset, got: {result.get('igv_params')}"
    )
    assert result.get("igv_params", {}).get("showCenterGuide") is True, (
        f"Expected showCenterGuide=True from user preset, got: {result.get('igv_params')}"
    )
    print("\n[S02/T03] ✓ test_intent_agent_user_preset_via_state passed")


def test_intent_agent_user_preset_overrides_builtin(monkeypatch):
    """User preset with same name as a builtin preset takes priority over the builtin."""
    import app.agents.graph as gm

    monkeypatch.setattr(gm, "USE_LLM", False)

    # Message contains 'sv' — a BUILTIN_PRESETS key — so preset='sv' is set by the loop.
    # user_presets also has 'sv', so the user_presets branch fires first (line 177-178),
    # overriding the builtin's trackHeight=120 with the user's trackHeight=999.
    state = {
        "message": "switch to sv preset",
        "region": None,
        "bam_path": "",
        "intent": "",
        "igv_params": {},
        "user_presets": {"sv": {"trackHeight": 999}},
        "response": "",
    }
    result = gm.intent_agent(state)
    assert result.get("intent") == "adjust_igv", (
        f"Expected intent='adjust_igv', got: {result.get('intent')!r}"
    )
    assert result.get("igv_params", {}).get("trackHeight") == 999, (
        f"Expected trackHeight=999 (user preset overrides builtin 120), "
        f"got: {result.get('igv_params')}"
    )
    print("\n[S02/T03] ✓ test_intent_agent_user_preset_overrides_builtin passed")


def test_intent_agent_extracts_multiple_bam_paths_into_tracks(monkeypatch):
    """Free-text path mode prompt with two BAM paths yields two bam_tracks with ordinal names."""
    import app.agents.graph as gm

    monkeypatch.setattr(gm, "USE_LLM", False)

    state = {
        "message": "Load first.bam and second.bam",
        "region": "20:59000-61000",
        "bam_path": "",
        "intent": "",
        "response": "",
    }

    result = gm.intent_agent(state)
    bam_tracks = result.get("bam_tracks", [])

    assert len(bam_tracks) == 2, f"Expected 2 bam_tracks, got: {bam_tracks}"
    assert bam_tracks[0]["bam_path"] == "first.bam"
    assert bam_tracks[1]["bam_path"] == "second.bam"
    assert bam_tracks[0]["sample_name"] == "sample_1"
    assert bam_tracks[1]["sample_name"] == "sample_2"
    print("\n[S02/T03] ✓ test_intent_agent_extracts_multiple_bam_paths_into_tracks passed")


def test_intent_agent_extracts_multiple_bam_paths_from_bam_path_field(monkeypatch):
    """Path input containing multiple BAMs should also materialize bam_tracks in order."""
    import app.agents.graph as gm

    monkeypatch.setattr(gm, "USE_LLM", False)

    state = {
        "message": "analyze this",
        "region": "20:59000-61000",
        "bam_path": "first.bam, second.bam",
        "intent": "",
        "response": "",
    }

    result = gm.intent_agent(state)
    bam_tracks = result.get("bam_tracks", [])

    assert len(bam_tracks) == 2, f"Expected 2 bam_tracks, got: {bam_tracks}"
    assert bam_tracks[0]["bam_path"] == "first.bam"
    assert bam_tracks[1]["bam_path"] == "second.bam"
    assert bam_tracks[0]["sample_name"] == "sample_1"
    assert bam_tracks[1]["sample_name"] == "sample_2"
    print("\n[S02/T03] ✓ test_intent_agent_extracts_multiple_bam_paths_from_bam_path_field passed")
