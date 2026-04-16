"""
Tests for edge payload contract and multi-BAM normalization.
"""
import pytest
from app.services.chat_contracts import (
    ChatContract,
    ContractError,
    normalize_chat_request,
    EdgePayload,
)


class TestSingleBAMEdgePayload:
    """Test backward-compatible single-BAM edge payloads (flat format)."""
    
    def test_valid_flat_edge_payload(self):
        """Single BAM with flat coverage/reads format."""
        request = ChatContract(
            message="analyze this",
            mode="edge",
            region="chr1:1-100",
            edge_payload={
                "coverage": [{"pos": 10, "depth": 5}],
                "reads": [{"name": "read1", "start": 5, "end": 20}],
            },
        )
        
        normalized = normalize_chat_request(request)
        
        assert normalized["mode"] == "edge"
        assert normalized["region"] == "chr1:1-100"
        assert len(normalized["coverage"]) == 1
        assert normalized["coverage"][0]["pos"] == 10
        assert len(normalized["reads"]) == 1
        assert normalized["reads"][0]["name"] == "read1"
        assert normalized.get("samples_metadata") is None
        assert normalized["bam_path"] == ""
    
    def test_flat_payload_missing_region(self):
        """Edge mode requires region."""
        request = ChatContract(
            message="analyze",
            mode="edge",
            edge_payload={"coverage": [], "reads": []},
        )
        
        with pytest.raises(ContractError, match="region is required"):
            normalize_chat_request(request)
    
    def test_flat_payload_missing_edge_payload(self):
        """Edge mode requires edge_payload."""
        request = ChatContract(
            message="analyze",
            mode="edge",
            region="chr1:1-100",
        )
        
        with pytest.raises(ContractError, match="edge_payload is required"):
            normalize_chat_request(request)
    
    def test_flat_payload_empty_coverage_and_reads(self):
        """Must have at least one coverage or read."""
        request = ChatContract(
            message="analyze",
            mode="edge",
            region="chr1:1-100",
            edge_payload={"coverage": [], "reads": []},
        )
        
        with pytest.raises(ContractError, match="at least one coverage or read"):
            normalize_chat_request(request)
    
    def test_flat_payload_invalid_coverage_item(self):
        """Coverage items must have pos and depth."""
        request = ChatContract(
            message="analyze",
            mode="edge",
            region="chr1:1-100",
            edge_payload={
                "coverage": [{"pos": 10}],  # Missing depth
                "reads": [],
            },
        )
        
        with pytest.raises(ContractError, match="'pos' and 'depth'"):
            normalize_chat_request(request)
    
    def test_flat_payload_invalid_read_item(self):
        """Read items must have name, start, end."""
        request = ChatContract(
            message="analyze",
            mode="edge",
            region="chr1:1-100",
            edge_payload={
                "coverage": [],
                "reads": [{"name": "read1", "start": 5}],  # Missing end
            },
        )
        
        with pytest.raises(ContractError, match="reads items must include"):
            normalize_chat_request(request)


class TestMultiBAMEdgePayload:
    """Test new multi-BAM edge payloads with samples dict."""
    
    def test_valid_two_sample_payload(self):
        """Two samples with coverage and reads."""
        request = ChatContract(
            message="compare samples",
            mode="edge",
            region="chr1:1-100",
            edge_payload={
                "samples": {
                    "sample1": {
                        "coverage": [{"pos": 10, "depth": 5}],
                        "reads": [{"name": "read1", "start": 5, "end": 20}],
                    },
                    "sample2": {
                        "coverage": [{"pos": 10, "depth": 8}],
                        "reads": [{"name": "read2", "start": 8, "end": 25}],
                    },
                }
            },
        )
        
        normalized = normalize_chat_request(request)
        
        assert normalized["mode"] == "edge"
        assert len(normalized["coverage"]) == 2
        assert len(normalized["reads"]) == 2
        assert normalized["samples_metadata"] == ["sample1", "sample2"]
    
    def test_multi_sample_with_empty_reads(self):
        """Multi-sample where one has only coverage."""
        request = ChatContract(
            message="analyze",
            mode="edge",
            region="chr1:1-100",
            edge_payload={
                "samples": {
                    "sample1": {
                        "coverage": [{"pos": 10, "depth": 5}],
                        "reads": [],
                    },
                    "sample2": {
                        "coverage": [{"pos": 10, "depth": 8}],
                        "reads": [{"name": "read2", "start": 8, "end": 25}],
                    },
                }
            },
        )
        
        normalized = normalize_chat_request(request)
        
        assert len(normalized["coverage"]) == 2
        assert len(normalized["reads"]) == 1
        assert normalized["samples_metadata"] == ["sample1", "sample2"]
    
    def test_multi_sample_with_sample_error(self):
        """Multi-sample payload may include error field per sample."""
        request = ChatContract(
            message="analyze",
            mode="edge",
            region="chr1:1-100",
            edge_payload={
                "samples": {
                    "sample1": {
                        "coverage": [{"pos": 10, "depth": 5}],
                        "reads": [],
                    },
                    "sample2": {
                        "coverage": [],
                        "reads": [],
                        "error": "BAI not found",
                    },
                }
            },
        )
        
        # Should normalize successfully even if one sample has an error field
        normalized = normalize_chat_request(request)
        assert normalized["samples_metadata"] == ["sample1", "sample2"]
    
    def test_multi_sample_empty_samples_dict(self):
        """Empty samples dict should be treated as flat format."""
        request = ChatContract(
            message="analyze",
            mode="edge",
            region="chr1:1-100",
            edge_payload={
                "samples": {},
                "coverage": [{"pos": 10, "depth": 5}],
                "reads": [],
            },
        )
        
        # Empty samples dict should fall back to flat format
        normalized = normalize_chat_request(request)
        assert len(normalized["coverage"]) == 1
    
    def test_multi_sample_invalid_sample_type(self):
        """Sample value must be a dict - Pydantic validates this at request level."""
        from pydantic import ValidationError
        
        with pytest.raises(ValidationError):
            ChatContract(
                message="analyze",
                mode="edge",
                region="chr1:1-100",
                edge_payload={
                    "samples": {
                        "sample1": [{"pos": 10, "depth": 5}],  # Array instead of dict
                    }
                },
            )
    
    def test_multi_sample_invalid_coverage_array(self):
        """Coverage within sample must be array - Pydantic validates this at request level."""
        from pydantic import ValidationError
        
        with pytest.raises(ValidationError):
            ChatContract(
                message="analyze",
                mode="edge",
                region="chr1:1-100",
                edge_payload={
                    "samples": {
                        "sample1": {
                            "coverage": "not_an_array",
                            "reads": [],
                        },
                    }
                },
            )
    
    def test_multi_sample_invalid_read_item(self):
        """Invalid read item within sample fails validation."""
        request = ChatContract(
            message="analyze",
            mode="edge",
            region="chr1:1-100",
            edge_payload={
                "samples": {
                    "sample1": {
                        "coverage": [],
                        "reads": [{"name": "read1"}],  # Missing start and end
                    },
                }
            },
        )
        
        with pytest.raises(ContractError, match="reads items must include"):
            normalize_chat_request(request)
    
    def test_multi_sample_all_empty(self):
        """All samples empty should raise error."""
        request = ChatContract(
            message="analyze",
            mode="edge",
            region="chr1:1-100",
            edge_payload={
                "samples": {
                    "sample1": {"coverage": [], "reads": []},
                    "sample2": {"coverage": [], "reads": []},
                }
            },
        )
        
        with pytest.raises(
            ContractError, match="samples must contain at least one sample with"
        ):
            normalize_chat_request(request)
    
    def test_multi_sample_samples_not_dict(self):
        """Samples value must be dict, not array - Pydantic validates at request level."""
        from pydantic import ValidationError
        
        with pytest.raises(ValidationError):
            ChatContract(
                message="analyze",
                mode="edge",
                region="chr1:1-100",
                edge_payload={"samples": [{"name": "sample1"}]},
            )


class TestPathMode:
    """Verify path mode is unchanged."""
    
    def test_path_mode_normalization(self):
        """Path mode should work as before."""
        request = ChatContract(
            message="hello",
            mode="path",
            bam_path="/path/to/test.bam",
            region="chr1:1-100",
        )
        
        normalized = normalize_chat_request(request)
        
        assert normalized["mode"] == "path"
        assert normalized["bam_path"] == "/path/to/test.bam"
        assert normalized["region"] == "chr1:1-100"
        assert "coverage" not in normalized or normalized.get("coverage") is None
