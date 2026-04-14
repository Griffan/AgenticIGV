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

    python -m venv .venv
    
    source .venv/bin/activate

2. Install dependencies:
   
   pip install -r requirements.txt

3. Copy environment template and add your key (optional for basic summaries):

   cp .env.example .env

## Run
Start the API server:

uvicorn app.main:app --reload

Open http://localhost:8000 in your browser.

## Usage
1. Choose mode:
  - `Path`: provide BAM path (and optional FASTA path)
  - `Edge`: select local BAM + BAI files (drag/drop supported)
2. Enter a region (example: `20:59000-61000` or `chr1:1000-2000`).
3. Click "Load region" to populate tracks.
- **Chat with your data**: Ask questions like:
  - "Show me region 20:59000-61000"
  - "What's the coverage like?"
  - "How many reads are there?"
  - "What's the average mapping quality?"
  - "Are reads evenly distributed across strands?"

**Quick test with sample BAM:**
```
BAM: /home/griffan/LinuxStorage/Download/GitRepos/VerifyBamID/resource/test/test.bam
Region: 20:59000-61000
Chat: "Analyze the coverage in this region"
```

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
