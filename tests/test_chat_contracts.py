"""Compact contract tests focused on external behavior (not internal implementation details)."""

import pytest
from pydantic import ValidationError

from app.services.chat_contracts import ChatContract, ContractError, normalize_chat_request


def test_edge_flat_normalization_success():
    request = ChatContract(
        message="analyze",
        mode="edge",
        region="chr1:1-100",
        edge_payload={
            "coverage": [{"pos": 10, "depth": 5}],
            "reads": [{"name": "r1", "start": 5, "end": 20}],
        },
    )

    normalized = normalize_chat_request(request)
    assert normalized["mode"] == "edge"
    assert normalized["region"] == "chr1:1-100"
    assert len(normalized["coverage"]) == 1
    assert len(normalized["reads"]) == 1
    assert normalized.get("samples_metadata") is None
    assert normalized["bam_path"] == ""


@pytest.mark.parametrize(
    "contract_input, expected_error",
    [
        (
            ChatContract(message="analyze", mode="edge", edge_payload={"coverage": [], "reads": []}),
            "region is required",
        ),
        (
            ChatContract(message="analyze", mode="edge", region="chr1:1-100"),
            "edge_payload is required",
        ),
        (
            ChatContract(
                message="analyze",
                mode="edge",
                region="chr1:1-100",
                edge_payload={"coverage": [], "reads": []},
            ),
            "at least one coverage or read",
        ),
        (
            ChatContract(
                message="analyze",
                mode="edge",
                region="chr1:1-100",
                edge_payload={"coverage": [{"pos": 10}], "reads": []},
            ),
            "'pos' and 'depth'",
        ),
        (
            ChatContract(
                message="analyze",
                mode="edge",
                region="chr1:1-100",
                edge_payload={"coverage": [], "reads": [{"name": "r1"}]},
            ),
            "reads items must include",
        ),
    ],
)
def test_edge_flat_normalization_errors(contract_input, expected_error):
    with pytest.raises(ContractError, match=expected_error):
        normalize_chat_request(contract_input)


def test_edge_multi_sample_normalization_success():
    request = ChatContract(
        message="compare",
        mode="edge",
        region="chr20:1000-2000",
        edge_payload={
            "samples": {
                "tumor": {
                    "coverage": [{"pos": 1000, "depth": 20}],
                    "reads": [{"name": "t1", "start": 950, "end": 1100}],
                },
                "normal": {
                    "coverage": [{"pos": 1000, "depth": 10}],
                    "reads": [{"name": "n1", "start": 960, "end": 1080}],
                },
            }
        },
    )

    normalized = normalize_chat_request(request)
    assert normalized["samples_metadata"] == ["tumor", "normal"]
    assert len(normalized["coverage"]) == 2
    assert len(normalized["reads"]) == 2


def test_edge_multi_sample_all_empty_errors():
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

    with pytest.raises(ContractError, match="samples must contain at least one sample"):
        normalize_chat_request(request)


@pytest.mark.parametrize(
    "edge_payload",
    [
        {"samples": {"sample1": [{"pos": 10, "depth": 5}] }},
        {"samples": [{"name": "sample1"}]},
    ],
)
def test_edge_multi_sample_pydantic_shape_validation(edge_payload):
    with pytest.raises(ValidationError):
        ChatContract(
            message="analyze",
            mode="edge",
            region="chr1:1-100",
            edge_payload=edge_payload,
        )


@pytest.mark.parametrize(
    "message, bam_path, expected_bam_path",
    [
        ("hello", "/path/to/test.bam", "/path/to/test.bam"),
        (
            'Load "/tmp/first.bam" and "/tmp/second.bam" in region chr1:1-100',
            "/tmp/second.bam",
            "/tmp/first.bam, /tmp/second.bam",
        ),
        ("analyze this", "/tmp/first.bam, /tmp/second.bam", "/tmp/first.bam, /tmp/second.bam"),
    ],
)
def test_path_mode_bam_selection_priority(message, bam_path, expected_bam_path):
    request = ChatContract(
        message=message,
        mode="path",
        bam_path=bam_path,
        region="chr1:1-100",
    )

    normalized = normalize_chat_request(request)
    assert normalized["mode"] == "path"
    assert normalized["region"] == "chr1:1-100"
    assert normalized["bam_path"] == expected_bam_path
