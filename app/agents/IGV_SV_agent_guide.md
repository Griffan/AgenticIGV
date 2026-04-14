# IGV Structural Variant (SV) Review Guide for Agent Workflows

This document is a detailed, implementation-oriented guide distilled from Illumina DRAGEN v4.4 documentation:

- Source: https://help.dragen.illumina.com/product-guide/dragen-v4.4/dragen-dna-pipeline/sv-calling/sv-igv-tutorial
- Topic: **Structural Variant IGV Tutorial**

It is written for agent-assisted review and chat workflows (not a verbatim copy of the original).

---

## 1) Purpose and scope

Use this guide when reviewing structural variant evidence in IGV with DRAGEN SV outputs.

Primary goals:
- Load BAM/VCF correctly
- Configure IGV to expose SV signals
- Recognize read-level signatures for INS/DEL/INV/BND
- Separate likely true events from common false-positive patterns

Important caveat from the tutorial context:
- There is no one-size-fits-all rule for SV interpretation.
- Patterns are heuristic and should be combined with sample context, region mappability, and QC.

---

## 2) Required inputs and setup

### 2.1 Inputs
- Alignment BAM from DRAGEN SV run (`prefix.bam`) plus index (`.bai`)
- SV VCF (`prefix.sv.vcf.gz`) and index (`.tbi`)
- Matching reference genome build

### 2.2 Critical pre-check
- Ensure the IGV reference matches the reference used during mapping/SV calling.
  - Mismatched builds can create misleading split-read and coverage artifacts.

### 2.3 IGV view components to monitor
- Top: reference genome + coordinates
- Middle: loaded tracks (alignment + SV calls)
- Bottom: sequence and gene annotation tracks
  - Sequence track helps identify repetitive context
  - RefSeq genes help evaluate potential functional impact

---

## 3) High-value IGV alignment configurations

These settings are repeatedly emphasized for SV evidence discovery.

### 3.1 Show mismatch + soft clipping
- Path: `View -> Preferences -> Alignments`
- Enable mismatch and soft-clip visibility
- Why it matters:
  - Soft clips and mismatch clusters often localize breakpoints
  - Novel sequence segments can indicate non-reference sequence

### 3.2 View as pairs
- Right-click alignment track -> `View as pairs`
- Why it matters:
  - Clarifies pair relationships and orientation evidence

### 3.3 Display mode = squished
- Right-click track -> `Squished`
- Why it matters:
  - Increases read density visible per screen

### 3.4 Group by chromosome of mate
- Right-click track -> Group alignments by `chromosome of mate`
- Why it matters:
  - Separates unpaired/unmapped/different-chromosome mate classes
- Note:
  - IGV does not show all remote/unmapped mate sequences in current locus context

### 3.5 Color by pair orientation and insert size
- Right-click track -> Color by `pair orientation and insert size`
- Why it matters:
  - Highlights discordant orientation
  - Flags too-short and too-long insert size pairs
- Practical interpretation:
  - Larger-than-expected inserts support deletions
  - Smaller-than-expected inserts can support duplications

### 3.6 Set insert-size thresholds
- Right-click track -> `Set insert size options...`
- Use absolute values or percentile-based cutoffs
- Common practical default from tutorial context: ~5th/95th percentile

### 3.7 Color by read strand
- Right-click track -> Color by strand
- Useful for visual strand-bias checks and orientation intuition

### 3.8 Split-screen mate region
- Right-click alignment -> `View mate region in split screen`
- Essential for translocations and distant mate evidence

---

## 4) Discordant-read evidence model for SV hypotheses

A read pair is discordant if one or more are true:
- Unexpected orientation
- Unexpected insert size (too long/too short)
- Clipping/large event in one or both reads
- Unmapped mate

Each SV class produces a characteristic mixture of these discordant signals.

---

## 5) SV-type interpretation patterns

## 5.1 Simple insertions
Expected evidence:
- Clipped reads piling up near breakpoints
- Reads with unmapped mates around event
- Potential missing full pair visualization for fully novel inserted sequence

Helpful settings:
- Group by chromosome of mate
- Color by strand
- View as pairs
- Color by insert size/orientation

Interpretation note:
- Novel inserted sequence can appear as soft clipping/unmapped mate behavior rather than clean mapped insertion sequence.

### 5.2 Insertions with flank homology (HOMSEQ)
Key behavior:
- Breakpoint ambiguity due to duplicated/homologous flank sequence
- Clipping can appear at two nearby locations
- Local coverage bump may occur in homologous segment

VCF fields to inspect:
- `HOMLEN`, `HOMSEQ`, `CIPOS`

Interpretation note:
- Exact breakpoint representation may be ambiguous; equivalent representations can exist.

### 5.3 Tandem duplication insertions
Typical signals:
- Noisy alignments in repeated context
- Discordant orientations
- Abnormal insert sizes
- Regional coverage increase

Interpretation note:
- Repeat structure can inflate ambiguity and mapping uncertainty.

### 5.4 Deletions
Typical signals:
- Elevated long-insert discordant pairs spanning event
- Coverage drop within deleted segment
- Split-read support at boundaries

VCF fields to inspect:
- `SVLEN`, `CIGAR`, `CIPOS`, `CIEND`, `HOMLEN`, `HOMSEQ`
- `VF` (variant-support vs reference-support read counts)

Genotype consistency checks:
- Heterozygous DEL often shows mixed support (ref + alt)
- Homozygous DEL often shows dominant alt support and near-absent ref support

### 5.5 Inversions
Typical signals:
- Mis-oriented pair clusters, especially `LL` and `RR` groups
- Often with flanking clipping/homology complexity

Helpful settings:
- Group by orientation
- Color by insert size and orientation

### 5.6 Translocations (BND/BND pair)
Typical signals:
- Mate pairs mapping between two chromosomes
- BND calls linked via `MATEID`
- Strong cross-chromosome mate group enrichment

Workflow:
1. Open one breakend locus
2. Use split-screen to open mate locus
3. Group by chromosome of mate
4. View as pairs and color by orientation/insert size

---

## 6) False-positive (FP) pattern catalog

The tutorial highlights common FP drivers and visual anti-patterns.

### 6.1 FP deletions
Common signs:
- No clear breakpoint pileups
- Weak or inconsistent coverage drop
- Evidence driven by a small subset of unusual fragments only
- Repetitive sequence context causing mapping ambiguity

### 6.2 FP insertions
Common signs:
- Highly repetitive/mobile-element-like contexts (e.g., noisy non-unique alignments)
- Very low number of supporting reads relative to local depth
- Poly-base artifacts or sequencing-noise-like clipping patterns

Bottom line:
- Noisy repetitive regions can create discordant-like signatures without real SV.

---

## 7) Practical agent decision checklist

When user asks for “update stats” or “is this SV real?”, evaluate in this order:

1. **Reference integrity**
   - Is IGV reference build matched to BAM/VCF run?

2. **Evidence sufficiency**
   - Are there multiple independent evidence modes?
     - split reads
     - discordant orientation
     - insert-size shift
     - mate-chromosome grouping signal
     - coverage pattern

3. **Breakpoint consistency**
   - Are clipping clusters coherent and near reported breakpoints?
   - Are confidence intervals (`CIPOS`, `CIEND`) consistent with observed spread?

4. **Genotype/VAF plausibility**
   - Do `VF` or supporting-read counts align with expected zygosity?

5. **Context risk**
   - Is region repetitive/homologous/polynucleotide-rich?
   - Does pattern resemble known FP archetypes?

6. **Conclusion class**
   - High-confidence support
   - Ambiguous; needs orthogonal support
   - Likely FP from mapping/noise

---

## 8) Suggested chat-agent response schema

For consistency in your `IGV_SV_agent`, use this compact output shape:

```text
Region reviewed: <chr:start-end>
SV hypothesis: <INS|DEL|INV|BND|uncertain>
Key evidence:
- <bullet list>
Contradictory evidence:
- <bullet list>
Quality/context risks:
- <repeats, low complexity, low support, etc>
Provisional assessment: <supported|ambiguous|likely FP>
Next checks:
- <split-screen mate view / threshold adjustment / additional locus>
```

---

## 9) Field notes for DRAGEN VCF interpretation (quick reference)

Commonly useful fields in examples:
- `SVTYPE`, `SVLEN`, `END`
- `CIGAR`, `CONTIG`
- `CIPOS`, `CIEND`
- `HOMLEN`, `HOMSEQ`
- `MATEID` (for BND pairs)
- `VF` (variant/read support context)

Use these fields together with IGV visual evidence; avoid single-field conclusions.

---

## 10) Limits and escalation criteria

Escalate or mark uncertain when:
- Evidence is dominated by repetitive-context noise
- Breakpoints are broad/unstable and unsupported by split reads
- Orientation/insert-size signal is weak or contradictory
- Coverage effect does not match claimed event size/type
- Support count is too small relative to total depth

In such cases, recommend orthogonal review (alternate caller, long-read data, or targeted validation).

---

## 11) Attribution

This guide is derived from the Illumina DRAGEN documentation page listed above and rewritten as an operational agent guide for internal use.
