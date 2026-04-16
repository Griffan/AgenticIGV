"""
Integration test for /api/chat with multi-BAM edge payloads.
"""
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from types import SimpleNamespace

import app.main as main


class FakeLLM:
    """Fake LLM for testing without calling OpenAI."""
    def __init__(self, *args, **kwargs):
        pass

    def invoke(self, messages):
        system_prompt = getattr(messages[0], "content", "") if messages else ""
        if "Respond in JSON format" in system_prompt:
            # Return null region so the pre-set request region is preserved
            return SimpleNamespace(
                content='{"intent": "analyze_variant", "region": null, "reasoning": "test stub"}'
            )
        return SimpleNamespace(content="Test analysis complete.")


def test_chat_single_bam_edge_flat_format():
    """POST /api/chat with single-BAM edge payload (backward-compatible flat format)."""
    
    class DummyGraph:
        def invoke(self, payload):
            # Verify normalized payload structure
            assert payload.get("mode") == "edge"
            assert payload.get("region") == "chr1:1-100"
            assert isinstance(payload.get("coverage"), list)
            assert isinstance(payload.get("reads"), list)
            
            return {
                "response": "Analysis complete",
                "coverage": payload.get("coverage", []),
                "reads": payload.get("reads", []),
                "region": payload.get("region"),
            }
    
    with patch.object(main, "_graph", DummyGraph()):
        client = TestClient(main.app)
        response = client.post(
            "/api/chat",
            json={
                "message": "Analyze this region",
                "mode": "edge",
                "region": "chr1:1-100",
                "edge_payload": {
                    "coverage": [
                        {"pos": 10, "depth": 5},
                        {"pos": 20, "depth": 8},
                    ],
                    "reads": [
                        {"name": "read1", "start": 5, "end": 25},
                        {"name": "read2", "start": 15, "end": 35},
                    ],
                },
            },
        )
    
    assert response.status_code == 200
    data = response.json()
    assert data["response"] == "Analysis complete"
    assert len(data["coverage"]) == 2
    assert len(data["reads"]) == 2


def test_chat_multi_bam_edge_samples_format():
    """POST /api/chat with multi-BAM edge payload (new samples format)."""
    
    class DummyGraph:
        def invoke(self, payload):
            # Verify normalized multi-BAM payload
            assert payload.get("mode") == "edge"
            assert payload.get("region") == "chr20:1000-2000"
            
            # Coverage and reads should be flattened
            assert isinstance(payload.get("coverage"), list)
            assert isinstance(payload.get("reads"), list)
            
            # Sample metadata should be preserved
            samples_meta = payload.get("samples_metadata", [])
            assert "tumor" in samples_meta
            assert "normal" in samples_meta
            
            # Flattened: 2 coverage items per sample = 4 total
            assert len(payload.get("coverage", [])) == 4
            # Flattened: 2 reads per sample = 4 total
            assert len(payload.get("reads", [])) == 4
            
            return {
                "response": "Multi-sample analysis complete",
                "coverage": payload.get("coverage", []),
                "reads": payload.get("reads", []),
                "region": payload.get("region"),
            }
    
    with patch.object(main, "_graph", DummyGraph()):
        client = TestClient(main.app)
        response = client.post(
            "/api/chat",
            json={
                "message": "Compare tumor vs normal",
                "mode": "edge",
                "region": "chr20:1000-2000",
                "edge_payload": {
                    "samples": {
                        "tumor": {
                            "coverage": [
                                {"pos": 1000, "depth": 20},
                                {"pos": 1500, "depth": 18},
                            ],
                            "reads": [
                                {"name": "tumor_r1", "start": 900, "end": 1100},
                                {"name": "tumor_r2", "start": 1400, "end": 1600},
                            ],
                        },
                        "normal": {
                            "coverage": [
                                {"pos": 1000, "depth": 10},
                                {"pos": 1500, "depth": 12},
                            ],
                            "reads": [
                                {"name": "normal_r1", "start": 950, "end": 1050},
                                {"name": "normal_r2", "start": 1450, "end": 1550},
                            ],
                        },
                    }
                },
            },
        )
    
    assert response.status_code == 200
    data = response.json()
    assert data["response"] == "Multi-sample analysis complete"
    assert len(data["coverage"]) == 4  # 2 from each sample
    assert len(data["reads"]) == 4     # 2 from each sample


def test_chat_multi_bam_with_partial_data():
    """Multi-BAM where one sample has only coverage, another has only reads."""
    
    class DummyGraph:
        def invoke(self, payload):
            # Verify normalization preserves partial data
            coverage = payload.get("coverage", [])
            reads = payload.get("reads", [])
            
            # Total: 2 coverage + 1 read (from mixed samples)
            assert len(coverage) == 2
            assert len(reads) == 1
            
            return {
                "response": "Partial data analysis",
                "coverage": coverage,
                "reads": reads,
                "region": payload.get("region"),
            }
    
    with patch.object(main, "_graph", DummyGraph()):
        client = TestClient(main.app)
        response = client.post(
            "/api/chat",
            json={
                "message": "Analyze mixed data",
                "mode": "edge",
                "region": "chrX:5000-6000",
                "edge_payload": {
                    "samples": {
                        "sample_coverage_only": {
                            "coverage": [
                                {"pos": 5000, "depth": 15},
                                {"pos": 5500, "depth": 20},
                            ],
                            "reads": [],
                        },
                        "sample_reads_only": {
                            "coverage": [],
                            "reads": [
                                {"name": "orphan_read", "start": 5100, "end": 5400},
                            ],
                        },
                    }
                },
            },
        )
    
    assert response.status_code == 200
    data = response.json()
    assert data["response"] == "Partial data analysis"


def test_chat_multi_bam_error_response():
    """Multi-BAM with invalid payload should return 400."""
    client = TestClient(main.app)
    
    # Invalid: empty samples dict
    response = client.post(
        "/api/chat",
        json={
            "message": "Analyze",
            "mode": "edge",
            "region": "chr1:1-100",
            "edge_payload": {
                "samples": {
                    "empty_sample": {
                        "coverage": [],
                        "reads": [],
                    }
                }
            },
        },
    )
    
    assert response.status_code == 400
    assert "samples must contain at least one sample" in response.text.lower() or "coverage or read" in response.text.lower()


def test_chat_edge_mode_preserves_samples_metadata():
    """Samples metadata should be included in normalized payload for per-sample result tracking."""
    
    received_payload = {}
    
    class CaptureGraph:
        def invoke(self, payload):
            received_payload.update(payload)
            return {
                "response": "ok",
                "coverage": [],
                "reads": [],
                "region": payload.get("region"),
            }
    
    with patch.object(main, "_graph", CaptureGraph()):
        client = TestClient(main.app)
        response = client.post(
            "/api/chat",
            json={
                "message": "test",
                "mode": "edge",
                "region": "chr1:1-100",
                "edge_payload": {
                    "samples": {
                        "sample_A": {
                            "coverage": [{"pos": 10, "depth": 5}],
                            "reads": [],
                        },
                        "sample_B": {
                            "coverage": [{"pos": 10, "depth": 8}],
                            "reads": [],
                        },
                    }
                },
            },
        )
    
    assert response.status_code == 200
    # Verify samples_metadata was populated in normalized payload
    assert received_payload.get("samples_metadata") == ["sample_A", "sample_B"]


if __name__ == "__main__":
    test_chat_single_bam_edge_flat_format()
    print("✅ test_chat_single_bam_edge_flat_format passed")
    
    test_chat_multi_bam_edge_samples_format()
    print("✅ test_chat_multi_bam_edge_samples_format passed")
    
    test_chat_multi_bam_with_partial_data()
    print("✅ test_chat_multi_bam_with_partial_data passed")
    
    test_chat_multi_bam_error_response()
    print("✅ test_chat_multi_bam_error_response passed")
    
    test_chat_edge_mode_preserves_samples_metadata()
    print("✅ test_chat_edge_mode_preserves_samples_metadata passed")
    
    print("\n✅ All integration tests passed")
