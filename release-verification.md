# Release Verification

## Exact Commands Run
- `npm run build` (client built successfully using Vite and tsc)
- `node server/badminton/normalizers.test.js` (server provider bindings verified)
- `npm run dev` (Express backend and Vite HMR running)

## Test Counts
- 1 Server-side normalizer/provider binding test passed.
- 102 Provider-side contract validation tests (historic observation in isolated SQLite; pending confirmation on upstream repo run).

## Provider Endpoint Checks
- `GET /api/v1/health` -> OK (Normalizes snake_case to camelCase)
- `GET /api/v1/website/calendar` -> OK
- `GET /api/v1/website/model-contract` -> OK
- `GET /api/v1/website/active-participants` -> OK

## Visual Checks
- Desktop Check: Left-rail navigation, max-width layout container, 9 active surfaces checked.
- Mobile Check: Responsive sticky horizontal nav, reduced padding, scrollable bounds checked.

## Current Availability States
- **Calendar:** `Available`
- **Forecast Model:** `Available`
- **Predictions / Bracket Topology:** `Withheld` (due to `no_published_prerequisites` returned by upstream API)
- **Active Participants:** `Available` (e.g. Aaron CHIA / SOH Wooi Yik showing as CONFIRMED)

## Unresolved External Blockers
- The provider upstream database does not yet have parsed predictions/draw topologies committed. Awaiting model evaluation and snapshot persistence on the Render backend.

## Safeguards Confirmed
- Render/Neon environment variables were not altered.
- Browser exclusively calls proxy server; `BADMINTON_API_BASE_URL` is entirely server-side.
- Provider cadence, locks, and OOM safeguards remain fully intact as the website performs no public write/collection actions.
