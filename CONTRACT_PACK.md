# CONTRACT PACK

## Overview
This document defines the strict website-facing routes, publication boundaries, and non-fabrication rules for the BWF Supercomputer.

## Website-Facing Routes
The website uses these read-only provider routes as its canonical contracts:
- `GET /api/v1/website/calendar`
- `GET /api/v1/website/calendar/{calendar_entry_id}/draw-documents`
- `GET /api/v1/website/active-participants`
- `GET /api/v1/website/calendar/{calendar_entry_id}/brackets/{discipline}`
- `GET /api/v1/website/model-contract`
- `GET /api/v1/website/matches/{match_id}/forecast`
- `GET /api/v1/website/calendar/{calendar_entry_id}/simulation`

## Rules and Guidelines
- **Senior Scope Rule:** Exclude future junior/U-age, Para data, International Challenge, etc.
- **Bracket Lifecycle:** Render only when parser-validated and fully reconciled.
- **Model Prerequisites:** Forecasts require versioned model snapshot, declared input contract, and active evaluation status.
- **Non-fabrication Rule:** Do not infer brackets, probabilities, dates, venues, or countries from match rows.
- **Score Precedence:** A settled official result supersedes any previous forecast display.
- **Null Safety:** Missing optional fields become explicit null/unavailable states rather than `undefined` strings.

## Forecast Fields
A forecast must contain:
- Model key/version
- Input cutoff
- Generation time
- Participant win probabilities (must total 10,000 basis points)
- Confidence label
- Uncertainty summary
- Evidence contributors
- Provenance

## Simulation Prerequisites
- Safe canonical tournament link.
- Parser-validated and fully reconciled official bracket.
- Active evaluated model.
- Persisted published simulation snapshot.
