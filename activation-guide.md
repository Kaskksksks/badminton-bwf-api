# Activation Guide

## Current Capabilities
The website currently implements the full UI and typed integration for the 9 product surfaces (Command Desk, Match Centre, H2H, Players, Tournaments, Rankings, Methodology, Analyst, Accuracy). It correctly consumes the provider contracts through a safe server-only adapter that handles rate limits, caching, timeouts, and partial responses without exposing the provider URL or credentials to the browser. 

## External Production Migrations
The website is currently deployed, but fully populating the evidence surfaces requires the external provider to finalize its migrations:
1. `0005_official_draw_topology_contract.py`
2. `0006_evidence_gated_model_contracts.py`

## Remaining Actions
The following actions remain external to the website and must be performed on the Provider (Render/Neon):
1. Apply the Alembic migrations (`alembic upgrade head`) to the Neon production database.
2. Train, evaluate, and activate a genuine provider model.
3. Persist published forecast, head-to-head, and simulation snapshots.
4. Complete direct BWF PDF parser review and full canonical match reconciliation.

## Verification
To verify the provider release normally:
- Use the `Command Desk` on the website to observe API health, Database health, and the live status of the Calendar and Model Readiness contracts. 
- Ensure that the cadence, source budget, locks, and OOM safeguards of the provider remain unchanged.

## Important Note
Migration success on the database does not imply forecast availability. Forecasts will continue to show a `Withheld` state until a genuinely published snapshot for the specific match is emitted by the provider model.
