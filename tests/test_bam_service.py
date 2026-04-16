import pytest
from pathlib import Path

from app.services import bam


RESOURCE_DIR = Path(__file__).resolve().parent.parent / "resource"
RESOURCE_BAM = RESOURCE_DIR / "test.bam"


@pytest.mark.parametrize(
    "region, expected",
    [
        ("chr1:10-20", ("chr1", 10, 20)),
        ("20:59000..61000", ("20", 59000, 61000)),
    ],
)
def test_parse_region_valid(region, expected):
    assert bam.parse_region(region) == expected


@pytest.mark.parametrize(
    "region",
    [
        "chr1-10-20",
        "chr1:200-100",
        "chr1:0-100",
    ],
)
def test_parse_region_invalid(region):
    with pytest.raises(ValueError):
        bam.parse_region(region)


@pytest.mark.parametrize(
    "coverage, expected",
    [
        ([{"pos": 1, "depth": 2}, {"pos": 2, "depth": 4}], {"min": 2, "max": 4, "mean": 3.0}),
        ([], {"min": 0, "max": 0, "mean": 0}),
        ([{"pos": 1, "depth": 42}], {"min": 42, "max": 42, "mean": 42.0}),
    ],
)
def test_summarize_coverage(coverage, expected):
    assert bam.summarize_coverage(coverage) == expected


def test_smoke_resource_bam_service_calls():
    assert RESOURCE_BAM.exists(), f"Missing smoke fixture: {RESOURCE_BAM}"

    coverage = bam.get_coverage(str(RESOURCE_BAM), "20:59000-61000")
    reads = bam.get_reads(str(RESOURCE_BAM), "20:59000-61000")

    assert isinstance(coverage, list)
    assert isinstance(reads, list)


def test_get_coverage_returns_igv_compatible_format():
    assert RESOURCE_BAM.exists(), f"Missing smoke fixture: {RESOURCE_BAM}"
    coverage = bam.get_coverage(str(RESOURCE_BAM), "20:59000-61000")
    assert isinstance(coverage, list), "get_coverage must return a list"
    assert len(coverage) > 0, "get_coverage must return non-empty list for valid region"

    for point in coverage:
        assert set(point.keys()) == {"pos", "depth"}, (
            f"Coverage point has unexpected keys: {set(point.keys())}"
        )
        assert isinstance(point["pos"], int) and point["pos"] > 0
        assert isinstance(point["depth"], int) and point["depth"] >= 0


def test_get_reads_no_sensitive_fields():
    assert RESOURCE_BAM.exists(), f"Missing smoke fixture: {RESOURCE_BAM}"
    FORBIDDEN = {"sequence", "qual", "query_sequence", "base_qualities", "raw_sequence"}
    reads = bam.get_reads(str(RESOURCE_BAM), "20:59000-61000")
    assert len(reads) > 0, "Expected non-empty reads list"

    for read in reads:
        leaked = FORBIDDEN & set(read.keys())
        assert not leaked, f"get_reads returned sensitive field(s): {leaked}"
        # Required IGV-contract keys
        assert "name" in read
        assert "start" in read and isinstance(read["start"], int)
        assert "end" in read and isinstance(read["end"], int)
        assert read["end"] >= read["start"]
        assert read.get("strand") in ("+", "-"), f"Invalid strand: {read.get('strand')}"


def test_get_reads_max_reads_cap():
    assert RESOURCE_BAM.exists(), f"Missing smoke fixture: {RESOURCE_BAM}"
    reads_capped = bam.get_reads(str(RESOURCE_BAM), "20:59000-61000", max_reads=5)
    assert len(reads_capped) <= 5, (
        f"Expected at most 5 reads, got {len(reads_capped)}"
    )


def test_ensure_bam_ready_missing_file():
    with pytest.raises(FileNotFoundError):
        bam.ensure_bam_ready("/nonexistent/path/test.bam")
