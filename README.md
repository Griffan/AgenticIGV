# Agentic IGV

A LangGraph-powered, multi-agent chat assistant for visualizing BAM alignment files. Load a region, inspect coverage and read pileups, and ask for context in natural language.

## Features
- LangGraph multi-agent pipeline: intent parsing, BAM retrieval, response drafting
- **Intelligent chat interface**: Ask questions in natural language about your alignments
- FastAPI backend with chat and region endpoints
- IGV.js browser embedded in the UI for full alignment visualization
- Dual runtime modes:
  - `Path` mode: existing server-side BAM/BAI access via filesystem paths
  - `Edge` mode: browser-local BAM/BAI loading with local feature extraction for chat
- **Fully offline**: No network required after setup; IGV.js runs locally
- Supports custom FASTA references or reference-free viewing
- **LLM-powered analysis**: Get intelligent insights about coverage, reads, and quality (when OPENAI_API_KEY is set)

## Requirements
- Python 3.10+
- A BAM file with a matching .bai index
- Optional: FASTA reference file with .fai index for nucleotide display

## Setup

1. Create a virtual environment:

```{bash}
    python -m venv .venv
```

```{bash}
    source .venv/bin/activate
```

2. Install dependencies:

```{bash}
   pip install -r requirements.txt
```

3. Copy environment template and add your key (optional for basic summaries):

```{bash}
   cp .env.example .env
```

## Run

1. Start the API server

```{bash}
uvicorn app.main:app --reload --port 8000
```

2. SSH Tunneling (optional if running on a remote server)

```{bash}
ssh -L 8000:localhost:8000 user@remote-server-address
```

3. Access the UI

```{bash}
Open http://localhost:8000 in your browser.
```

## Usage
1. Choose mode:
  - `Path`: provide BAM path (and optional FASTA path)
  - `Edge`: select local BAM + BAI files (drag/drop supported)
2. Enter a region (example: `20:59000-61000` or `chr1:1000-2000`).
3. Click "Load region" to populate tracks.
- **Chat with your data**: Ask questions like:
  - "Load "resource/test.bam" and "resource/test2.bam" in region 20:56000-65000"
  - "Show me region 20:59000-61000"
  - "What's the coverage like?"
  - "How many reads are there?"
  - "What's the average mapping quality?"
  - "Are reads evenly distributed across strands?"

**Quick test with tracked sample BAM:**
```
BAM: resource/test.bam
FASTA: resource/chr20.fa
Region: 20:59000-61000
Chat: "Analyze the coverage in this region"
```

## Live browser proof (S03)

Run the end-to-end typed-control proof against the real FastAPI app in path mode with the checked-in script:

```bash
npm run test:e2e:live
```

Equivalent direct Playwright invocation:

```bash
OPENAI_API_KEY=dummy node_modules/.bin/playwright test tests/e2e/igv_control_live.spec.js
```

If you are targeting a single spec file, prefer the checked-in npm scripts or `node_modules/.bin/playwright ...`; `npm exec playwright test <spec>` can drop the positional spec argument under some npm versions.

What this live spec verifies:
- preset + override request applies in-browser and surfaces typed `control_resolution` rows
- partial-understanding request preserves parse-note/skipped feedback
- mixed control + analysis request still applies control while keeping visible SV analysis output

Troubleshooting browser dependencies on fresh Linux machines:
- install browser binaries: `npx playwright install --with-deps chromium`
- if Playwright reports missing shared libraries (for example `libnspr4.so`), run `npx playwright install-deps chromium`
- keep Playwright failure artifacts (`test-results/`) to inspect traces/screenshots for startup vs payload vs browser-application regressions

## Notes
- The BAM index must exist next to the BAM file (sample.bam.bai or sample.bai).
- Edge mode requires both `.bam` and `.bai` files loaded in the browser.
- In Edge mode, chat sends extracted region-level read/coverage signals to backend analysis (no server BAM path required).
- Edge mode keeps BAM parsing local in the browser; chat/variant response generation still runs through backend APIs.
- If using a FASTA reference, ensure the .fai index exists (create with `samtools faidx`).
- Coverage is capped to 2000 points for fast rendering.
- **LLM Chat Features**:
  - Without OPENAI_API_KEY: Basic pattern-matching responses
  - With OPENAI_API_KEY: Intelligent analysis and natural language understanding
  - The system works fully offline, LLM is optional for enhanced chat
- IGV.js runs completely offline using local files via /api/file and /api/index endpoints.
- IGV.js library is bundled in static/ and requires no external network calls.
