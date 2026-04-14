import pytest
from pathlib import Path

from app.services import bam


RESOURCE_DIR = Path(__file__).resolve().parent.parent / "resource"
RESOURCE_BAM = RESOURCE_DIR / "test.bam"


def test_parse_region_valid():
    contig, start, end = bam.parse_region("chr1:10-20")
    assert contig == "chr1"
    assert start == 10
    assert end == 20


def test_parse_region_invalid():
    with pytest.raises(ValueError):
        bam.parse_region("chr1-10-20")


def test_summarize_coverage():
    summary = bam.summarize_coverage(
        [{"pos": 1, "depth": 2}, {"pos": 2, "depth": 4}]
    )
    assert summary == {"min": 2, "max": 4, "mean": 3.0}


def test_smoke_resource_bam_service_calls():
    assert RESOURCE_BAM.exists(), f"Missing smoke fixture: {RESOURCE_BAM}"

    coverage = bam.get_coverage(str(RESOURCE_BAM), "20:59000-61000")
    reads = bam.get_reads(str(RESOURCE_BAM), "20:59000-61000")

    assert isinstance(coverage, list)
    assert isinstance(reads, list)


# ─────────────────────────────────────────────────────────────────────────────
# T04: Additional BAM service boundary and integration tests
# ─────────────────────────────────────────────────────────────────────────────

def test_parse_region_boundary_cases():
    """parse_region handles edge cases: dotdot separator, bare numeric contig."""
    from app.services.bam import parse_region

    # dotdot separator (e.g., samtools-style 20:59000..61000)
    contig, start, end = parse_region("20:59000..61000")
    assert contig == "20"
    assert start == 59000
    assert end == 61000

    # Chromosome with 'chr' prefix
    contig2, start2, end2 = parse_region("chr1:1-100")
    assert contig2 == "chr1"
    assert start2 == 1
    assert end2 == 100


def test_parse_region_invalid_coords():
    """parse_region raises ValueError for semantically invalid coordinates."""
    import pytest
    from app.services.bam import parse_region

    with pytest.raises(ValueError):
        parse_region("chr1:200-100")  # end < start

    with pytest.raises(ValueError):
        parse_region("chr1:0-100")  # start < 1


def test_summarize_coverage_empty():
    """summarize_coverage of empty list returns zero values without crashing."""
    from app.services.bam import summarize_coverage

    result = summarize_coverage([])
    assert result == {"min": 0, "max": 0, "mean": 0}


def test_summarize_coverage_single_point():
    """summarize_coverage with one point yields identical min/max/mean."""
    from app.services.bam import summarize_coverage

    result = summarize_coverage([{"pos": 1, "depth": 42}])
    assert result["min"] == 42
    assert result["max"] == 42
    assert result["mean"] == 42.0


def test_get_coverage_returns_igv_compatible_format():
    """get_coverage returns a list of {pos, depth} dicts usable by IGV.js."""
    assert RESOURCE_BAM.exists(), f"Missing smoke fixture: {RESOURCE_BAM}"

    from app.services.bam import get_coverage

    coverage = get_coverage(str(RESOURCE_BAM), "20:59000-61000")
    assert isinstance(coverage, list), "get_coverage must return a list"
    assert len(coverage) > 0, "get_coverage must return non-empty list for valid region"

    for point in coverage:
        assert set(point.keys()) == {"pos", "depth"}, (
            f"Coverage point has unexpected keys: {set(point.keys())}"
        )
        assert isinstance(point["pos"], int) and point["pos"] > 0
        assert isinstance(point["depth"], int) and point["depth"] >= 0


def test_get_reads_no_sensitive_fields():
    """get_reads must not expose raw sequence, qual, or base-quality data."""
    assert RESOURCE_BAM.exists(), f"Missing smoke fixture: {RESOURCE_BAM}"

    from app.services.bam import get_reads

    FORBIDDEN = {"sequence", "qual", "query_sequence", "base_qualities", "raw_sequence"}
    reads = get_reads(str(RESOURCE_BAM), "20:59000-61000")
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
    """get_reads respects the max_reads cap to prevent unbounded memory growth."""
    assert RESOURCE_BAM.exists(), f"Missing smoke fixture: {RESOURCE_BAM}"

    from app.services.bam import get_reads

    reads_capped = get_reads(str(RESOURCE_BAM), "20:59000-61000", max_reads=5)
    assert len(reads_capped) <= 5, (
        f"Expected at most 5 reads, got {len(reads_capped)}"
    )


def test_ensure_bam_ready_missing_file():
    """ensure_bam_ready raises FileNotFoundError for non-existent BAM."""
    import pytest
    from app.services.bam import ensure_bam_ready

    with pytest.raises(FileNotFoundError):
        ensure_bam_ready("/nonexistent/path/test.bam")
