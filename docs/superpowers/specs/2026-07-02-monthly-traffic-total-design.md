# Monthly Traffic Total In UI

## Goal

Show the total client traffic consumed during the current calendar month without requiring the admin to manually add per-client values.

## Current Data

The backend already records per-client traffic deltas in SQLite and exposes current-month usage through existing status/history flows:

- `/api/status` returns each peer with `mrx` and `mtx`.
- `/api/history` returns current-month per-client rows in `clients`.

No new persistence, WireGuard collection, or privileged helper changes are needed.

## UI Design

Add a compact header pill near the live throughput pill. It will show current calendar-month traffic as down, up, and combined total, for example:

`Month ↓ 12.3 GiB ↑ 4.8 GiB · 17.1 GiB`

The pill should use the existing down/up colors and tooltip/i18n mechanism. If no usage has been recorded yet, it should still render with zero values rather than disappearing.

Also add the same monthly total summary at the top of the `Usage` modal, above the daily chart and client breakdown. This keeps the main-screen value and detailed history view consistent.

## Data Flow

On each `/api/status` tick, the frontend sums `peers[].mrx` and `peers[].mtx` to update the header pill.

When opening `Usage`, the frontend sums `clients[].rx` and `clients[].tx` from `/api/history` and renders the modal total. This avoids coupling the modal to the last status poll and works even if the modal is opened before the first successful status tick.

## Error Handling

If status polling fails, the last rendered header value remains until reconnect. If history loading fails, the existing modal error behavior remains unchanged.

## Testing

Add focused frontend unit coverage for the monthly-total calculation/formatting helper if the repository has a practical JavaScript test entry point. Otherwise add Python unit coverage for backend monthly totals only if backend shape changes become necessary.

Run the existing unit suite after implementation.
