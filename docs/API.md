# API Reference

This document describes the current public backend contract for AgenticIGV, with emphasis on the typed `/api/chat` response boundary consumed by the frontend.

## Endpoints

### `GET /api/health`
Returns service status.

```json
{ "status": "ok" }
```

### `GET /api/bam/chromosomes?bam_path=<path>`
Reads BAM header and returns contigs:

```json
{
  "chromosomes": [
    { "name": "chr20", "length": 63025520, "index": 0 }
  ]
}
```

### `GET|HEAD /api/file?path=<path>`
Streams arbitrary tracked files (supports HTTP range requests).

### `GET|HEAD /api/index?bam_path=<path>`
Streams BAM index (`.bai`) for a BAM file.

### `POST /api/region`
Returns coverage + reads for a region (currently `mode=path` only).

Request:

```json
{
  "bam_path": "resource/test.bam",
  "region": "20:59000-61000",
  "mode": "path"
}
```

Response:

```json
{
  "coverage": [{ "pos": 59000, "depth": 12 }],
  "reads": [{ "name": "r1", "start": 59000, "end": 59075 }]
}
```

---

## `POST /api/chat`

### Request model (`ChatRequest`)
`ChatRequest` extends `ChatContract`.

```json
{
  "message": "switch to sv preset and analyze this region",
  "mode": "path",
  "bam_path": "resource/test.bam",
  "fasta_path": "resource/chr20.fa",
  "region": "20:59000-61000",
  "edge_payload": null
}
```

### Response model (`ChatResponse`)

`/api/chat` now returns a typed, nested control payload (`control_resolution`) and additive compatibility fields (`igv_params`, `igv_feedback`, `preset`) derived from the same control payload when present.

```json
{
  "response": "Preset 'sv' applied with overrides: {'trackHeight': 180}",
  "coverage": [],
  "reads": [],
  "region": "20:59000-61000",
  "variant_assessment": {},
  "metrics": {},
  "sv_present": null,
  "sv_type": null,
  "sv_confidence": null,
  "sv_evidence": [],

  "control_resolution": {
    "preset": "sv",
    "preset_source": "resource",
    "preset_path": ".../resource/igv_presets/sv.json",
    "base_igv": {
      "trackHeight": 120,
      "showCenterGuide": true,
      "minMapQuality": 20
    },
    "resolved_igv": {
      "trackHeight": 180,
      "showCenterGuide": true,
      "minMapQuality": 20
    },
    "applied": [
      {
        "key": "preset:sv",
        "action": "applied",
        "reason": "Loaded preset asset",
        "value": ".../resource/igv_presets/sv.json"
      },
      {
        "key": "trackHeight",
        "action": "applied",
        "reason": "Applied direct override",
        "value": 180
      }
    ],
    "skipped": [],
    "failed": [],
    "parse_notes": []
  },

  "igv_params": {
    "trackHeight": 180,
    "showCenterGuide": true,
    "minMapQuality": 20
  },
  "igv_feedback": "Preset 'sv' applied with overrides: {...}",
  "preset": "sv",

  "bam_tracks": [],
  "per_track_results": {}
}
```

### Typed control model details

#### `control_resolution`
- `preset: string | null` — requested preset name.
- `preset_source: string` — one of current resolver sources (`resource`, `missing`, `invalid`, `none`).
- `preset_path: string | null` — tracked preset asset path when loaded.
- `base_igv: object` — baseline IGV params from preset asset.
- `resolved_igv: object` — final deterministic params after overlays + overrides.
- `applied: ControlResultItem[]`
- `skipped: ControlResultItem[]`
- `failed: ControlResultItem[]`
- `parse_notes: string[]`

#### `ControlResultItem`
- `key: string`
- `action: "applied" | "skipped" | "failed"`
- `reason: string`
- `value?: any`

### Failure semantics

- Unknown preset requests are explicit in `control_resolution.failed` (e.g. `key = "preset:nope"`) and reflected in compatibility feedback (`"Preset 'nope' not recognized."`).
- Invalid/malformed `control_resolution` objects from internal graph output fail API contract validation (HTTP 400) rather than silently drifting schema.
- Compatibility fields are additive only:
  - `igv_params` mirrors `control_resolution.resolved_igv`
  - `preset` mirrors `control_resolution.preset`
  - `igv_feedback` is preserved when provided, otherwise deterministically derived from typed control resolution

### Redaction and boundary constraints

- Only versioned preset names, allowed IGV keys, and tracked preset paths are serialized.
- No secret values or arbitrary filesystem reads are surfaced by the contract.
