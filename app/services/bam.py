import os
import re
from typing import Any, Dict, List, Tuple, cast

import pysam


REGION_RE = re.compile(r"^(?P<contig>[^:]+):(?P<start>\d+)[-\.]{1,2}(?P<end>\d+)$")
MAX_REGION_LEN = 2000


def parse_region(region: str) -> Tuple[str, int, int]:
    match = REGION_RE.match(region.strip())
    if not match:
        raise ValueError("Region must look like chr1:100-200")
    contig = match.group("contig")
    start = int(match.group("start"))
    end = int(match.group("end"))
    if start < 1 or end < 1 or end < start:
        raise ValueError("Region coordinates are invalid")
    return contig, start, end


def ensure_bam_ready(bam_path: str) -> None:
    if not os.path.exists(bam_path):
        raise FileNotFoundError("BAM file not found")
    if not (os.path.exists(bam_path + ".bai") or os.path.exists(bam_path.replace(".bam", ".bai"))):
        raise FileNotFoundError("BAM index (.bai) not found")


def _limit_region(start: int, end: int) -> Tuple[int, int, int]:
    length = end - start + 1
    if length <= MAX_REGION_LEN:
        return start, end, 1
    step = max(1, length // MAX_REGION_LEN)
    return start, end, step


def _resolve_contig_name(bam: pysam.AlignmentFile, contig: str) -> str:
    references = set(bam.references)
    if contig in references:
        return contig
    if contig.startswith("chr"):
        alternate = contig[3:]
    else:
        alternate = f"chr{contig}"
    if alternate in references:
        return alternate
    raise ValueError(f"invalid contig `{contig}`")


def get_coverage(bam_path: str, region: str) -> List[Dict[str, Any]]:
    ensure_bam_ready(bam_path)
    contig, start, end = parse_region(region)
    start, end, step = _limit_region(start, end)
    coverage: List[Dict[str, Any]] = []
    with pysam.AlignmentFile(bam_path, "rb") as bam:
        if not bam.has_index():
            raise FileNotFoundError("BAM index (.bai) not found")
        resolved_contig = _resolve_contig_name(bam, contig)
        for pileup_column in bam.pileup(resolved_contig, start - 1, end, truncate=True, stepper="all"):
            column = cast(Any, pileup_column)
            pos = column.reference_pos + 1
            if pos < start or pos > end:
                continue
            if step > 1 and (pos - start) % step != 0:
                continue
            coverage.append({"pos": pos, "depth": column.nsegments})
    return coverage


def get_reads(bam_path: str, region: str, max_reads: int = 200) -> List[Dict[str, Any]]:
    ensure_bam_ready(bam_path)
    contig, start, end = parse_region(region)
    reads: List[Dict[str, Any]] = []

    def _pair_orientation(read: pysam.AlignedSegment) -> str:
        if not read.is_paired:
            return "SINGLE"
        if read.mate_is_unmapped:
            return "UNKNOWN"
        if read.is_reverse and read.mate_is_reverse:
            return "RR"
        if (not read.is_reverse) and (not read.mate_is_reverse):
            return "LL"
        if (not read.is_reverse) and read.mate_is_reverse:
            return "LR"
        return "RL"

    def _cigar_signal(read: pysam.AlignedSegment) -> Dict[str, int]:
        soft_clip_bases = 0
        insertion_bases = 0
        deletion_bases = 0
        if read.cigartuples:
            for op, length in read.cigartuples:
                if op == 4:
                    soft_clip_bases += length
                elif op == 1:
                    insertion_bases += length
                elif op == 2:
                    deletion_bases += length
        return {
            "soft_clip_bases": soft_clip_bases,
            "insertion_bases": insertion_bases,
            "deletion_bases": deletion_bases,
        }

    with pysam.AlignmentFile(bam_path, "rb") as bam:
        if not bam.has_index():
            raise FileNotFoundError("BAM index (.bai) not found")
        resolved_contig = _resolve_contig_name(bam, contig)
        for read in bam.fetch(resolved_contig, start - 1, end):
            if read.is_unmapped:
                continue
            cigar_signal = _cigar_signal(read)
            mate_chromosome = "UNMAPPED" if read.mate_is_unmapped else read.next_reference_name
            reads.append(
                {
                    "name": read.query_name,
                    "start": read.reference_start + 1,
                    "end": read.reference_end,
                    "cigar": read.cigarstring,
                    "strand": "-" if read.is_reverse else "+",
                    "mapq": read.mapping_quality,
                    "is_paired": read.is_paired,
                    "mate_chromosome": mate_chromosome,
                    "mate_start": None if read.next_reference_start < 0 else read.next_reference_start + 1,
                    "insert_size": abs(read.template_length),
                    "pair_orientation": _pair_orientation(read),
                    "soft_clip_bases": cigar_signal["soft_clip_bases"],
                    "insertion_bases": cigar_signal["insertion_bases"],
                    "deletion_bases": cigar_signal["deletion_bases"],
                    "has_soft_clip": cigar_signal["soft_clip_bases"] > 0,
                }
            )
            if len(reads) >= max_reads:
                break
    return reads


def summarize_coverage(coverage: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not coverage:
        return {"min": 0, "max": 0, "mean": 0}
    depths = [point["depth"] for point in coverage]
    total = sum(depths)
    return {
        "min": min(depths),
        "max": max(depths),
        "mean": round(total / len(depths), 2),
    }
