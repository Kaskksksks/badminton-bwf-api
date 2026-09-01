# Project Status

## Branch Inventory
- Active Branch: `frontend-update`
- Reused files: N/A (initialized from scratch as previous files were removed or not present).
- Known incomplete work: The deployed provider API (`https://badminton-bwf-api.onrender.com/api/v1`) currently returns HTTP 503 (Service Unavailable). The integration is built to handle this gracefully via explicit error and withheld states.

## Provider Access Status
- The BWF Provider API is currently offline/unavailable (HTTP 503). 
- All endpoints tested returned 503 Service Unavailable.

## Planned Implementation Sequence
1. Set up a split `client/` and `server/` architecture.
2. Build the server-only Express adapter with timeout, retry, and caching logic to handle the 503s gracefully.
3. Build the BWF Supercomputer visual shell and 9 required surfaces in React/Tailwind.
4. Integrate the client with the local server adapter.
5. Provide strict data provenance rules (all surfaces will gracefully show 'Unavailable' or 'Error' states right now due to the 503s).
