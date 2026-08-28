# BWF // Supercomputer Audit TODO

## Completed in this reconnaissance pass

- [x] Inspected the current public provider `main` branch and commit.
- [x] Inspected provider routes, typed website schemas, classifier, migrations, scheduler gates, and tests.
- [x] Probed safe read-only deployed endpoints and recorded successful, empty, withheld, 429, 502, and 503 behavior.
- [x] Verified the approved senior-only classifier and exclusions.
- [x] Created `PROJECT_STATUS.md`.
- [x] Created `ENDPOINT_INVENTORY.md`.
- [x] Created `CONTRACT_PACK.md`.
- [x] Created `PROVIDER_CAPABILITY_MATRIX.md`.
- [x] Created `HANDOFF_00_RECONNAISSANCE.md`.
- [x] Ran dependency-free Python compilation validation against the provider checkout.

## Pending provider-side verification

- [ ] Verify the deployed Alembic revision through an authorized operator path; do not infer it from source files.
- [ ] Verify Render scheduler/environment activation without changing settings.
- [ ] Complete controlled direct-PDF parser review and canonical node-to-match reconciliation.
- [ ] Verify a published, evaluated model snapshot and forecast snapshot before exposing forecast fields.
- [ ] Verify a canonical tournament link, reconciled topology, and published simulation snapshot before exposing simulations.
- [ ] Re-probe any currently rate-limited or transiently failing endpoint from an authorized/operational context.

## Pending website-side work

- [ ] Create the website server and browser application as a separate product artifact.
- [ ] Proxy all browser calls through the website server with the provider base URL server-side.
- [ ] Implement the explicit state model in `CONTRACT_PACK.md`.
- [ ] Add desktop/mobile surfaces for calendar, matches, participants, players, tournaments, and capability/readiness states.
- [ ] Keep rankings, brackets, forecasts, and simulations visibly withheld until provider contracts return populated validated data.
