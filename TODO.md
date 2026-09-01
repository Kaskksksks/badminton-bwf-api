# TODO

- [x] Inspect existing repositories/branches and project state.
- [x] Initialize client/server full-stack architecture with safe `server-only` proxy adapter.
- [x] Implement the 9 required intelligence surfaces (Command Desk, Match Centre, H2H Lab, Player Intelligence, Tournament Centre, Rankings Intelligence, Methodology, AI Analyst, Accuracy Ledger).
- [x] Implement the dark BWF Supercomputer visual theme using Tailwind CSS and specific tokens.
- [x] Integrate with upstream provider (`badminton-bwf-api.onrender.com/api/v1`).
- [x] Add graceful error and loading state handling for all surfaces (`CapabilityState`).
- [x] Ensure missing / unavailable data never leads to fabricated records in the UI (strict evidence bounds).
- [ ] Provider: Deploy current `main` branch to Render.
- [ ] Provider: Apply Neon DB migrations (`0005_official_draw_topology_contract.py`, `0006_evidence_gated_model_contracts.py`).
- [ ] Provider: Validate models, scheduling, parser routines, and predictions upstream.
