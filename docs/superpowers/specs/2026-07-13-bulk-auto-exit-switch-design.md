# Bulk and Automatic Exit Switching

## Goal

Add two related capabilities to WG Cascade:

1. Let the operator move every registered client from NL to US or from US to NL
   in one safe operation.
2. Optionally move every client automatically when the exit currently carrying
   assigned clients reaches its calendar-month traffic quota.

The reference deployment has two exits, `nl` (`wg-do`) and `us` (`wg-us`). Each
exit has an independently configurable quota, defaulting to 500 GiB.

## Product Decisions

- A quota is the sum of receive and transmit bytes for one exit during the
  current calendar month.
- Quotas are configured independently for NL and US in whole GiB.
- The allowed range is 1 through 1,000,000 GiB.
- Automatic switching triggers at `used >= quota`; there is no safety margin.
- Because usage is persisted approximately once per minute, the measured total
  can exceed the quota by up to one sampling interval of traffic.
- A switch updates the entire registry, including disabled clients. Re-enabling
  a client therefore cannot return it to an exhausted exit.
- The target must have a fresh successful health check and must still be below
  its own quota.
- If the target is unavailable, stale, or exhausted, clients remain on the
  current exit and the UI shows a persistent critical message. The server keeps
  retrying the policy evaluation.
- Clients stay on their current exit when a new month begins. There is no
  automatic return to NL.
- Auto switch is controlled by a persistent UI toggle and is off by default on
  first deployment.
- Manual bulk switching uses the same health and quota guards as automatic
  switching. There is no force override.

## Why Exit Counters Must Change

The current UI derives each exit total by summing per-client monthly usage and
grouping clients by their *current* exit. After a client changes exit, that
approach incorrectly moves all of the client's earlier monthly traffic to the
new exit.

Quota accounting will instead use the cumulative transfer counters of the exit
tunnels themselves:

- NL: the peer on `wg-do`
- US: the peer on `wg-us`

The sampler already dumps both interfaces for health. It will retain their RX
and TX totals, persist deltas, and handle counter resets in the same manner as
the existing per-client accounting. Per-client usage remains unchanged for
client cards and history.

These are local WireGuard counters, not a hosting-provider billing API. They are
the best locally authoritative source, but a provider can account for protocol
overhead differently. Provider API integration is outside this change.

## Sources of Truth

| Concern | Source of truth |
| --- | --- |
| Client exit assignment | `/etc/wg-ui/clients.json` |
| Auto-switch setting and quotas | `/etc/wg-ui/exit-policy.json` |
| Current tunnel counters and health | `wg-do` / `wg-us` dumps and egress probes |
| Calendar-month exit usage | `/var/lib/wg-ui/history.db` |
| Persistent administrative history | `/var/lib/wg-ui/audit.log` |

`exit-policy.json` is written only by `wg-admin.py` as `0640 root:wgui`, so the
web service can read but cannot modify it. This preserves the existing
privileged-helper boundary. Its version 1 shape is:

```json
{
  "version": 1,
  "auto_switch": false,
  "quota_bytes": {
    "nl": 536870912000,
    "us": 536870912000
  }
}
```

Missing or invalid policy data fails safely to auto switch off and 500 GiB per
exit. The UI submits whole-GiB values; the helper validates the range and stores
exact byte values.

## Database Model and Migration

`db_init()` adds these tables without changing existing tables:

```sql
CREATE TABLE IF NOT EXISTS exit_usage(
  exit TEXT,
  day TEXT,
  rx INTEGER DEFAULT 0,
  tx INTEGER DEFAULT 0,
  PRIMARY KEY(exit, day)
);

CREATE TABLE IF NOT EXISTS exit_counters(
  exit TEXT PRIMARY KEY,
  rx INTEGER,
  tx INTEGER
);

CREATE TABLE IF NOT EXISTS schema_meta(
  key TEXT PRIMARY KEY,
  value TEXT
);
```

On the first upgraded start only:

1. Existing current-month per-client usage is grouped by day and by each
   client's current registry assignment, then copied into `exit_usage`.
2. The migration records `exit_usage_v1_seeded` in `schema_meta` so it cannot
   run twice.
3. The first available `wg-do` and `wg-us` totals become baselines in
   `exit_counters`; lifetime tunnel totals are never added to the current month.

The backfill preserves the value currently visible to the operator. It is exact
for the stated deployment, where all clients are still on NL. If a different
deployment switched clients earlier in the month, pre-upgrade attribution is a
best-effort estimate based on their assignment at migration time. All traffic
after migration is attributed directly from the exit tunnel counters.

Calendar-month totals query rows on or after the local first day of the current
month, matching the application's existing local-time usage model.

## Server Components

### Exit counter sampling

The exit peer parser returns handshake state plus cumulative RX and TX totals.
Approximately once per minute the sampler:

1. Persists per-exit deltas in `exit_usage`.
2. Updates `exit_counters` baselines.
3. Refreshes current-month exit totals.
4. Evaluates the automatic policy after the database commit.

If a cumulative counter is lower than its baseline, the interface or peer was
reset; the current counter is treated as the new delta. If no previous baseline
exists, the current sample establishes it and contributes zero bytes.

### Policy evaluator

The evaluator runs only when `auto_switch` is enabled. For each exit it derives:

- monthly used bytes;
- quota and exhausted state;
- count of registered clients assigned to it;
- health freshness and result.

An automatic action is eligible when:

1. A source exit has at least one assigned client.
2. Its usage is greater than or equal to its quota.
3. The other exit has a successful egress check no older than 60 seconds.
4. The other exit is below its quota.

The action always moves the full registry to the target, including clients
already on the target and disabled clients. Already-correct entries are no-ops.
After the move, the exhausted source has no assigned clients and cannot trigger
a switch back. If the new target later reaches its quota while the former source
is still exhausted, both exits are exhausted and the evaluator reports a block
instead of ping-ponging.

Policy evaluation and manual bulk requests share a process-level policy lock.
No application lock is held while invoking the root helper. The helper's
existing file lock provides cross-operation serialization.

Blocked state is deduplicated in memory to avoid repeated audit or log noise and
is exposed in status until conditions recover. The evaluator retries after each
usage persistence interval. `last_switch` and `blocked` are runtime status;
successful operations remain durably available in the audit log. After a
service restart, policy evaluation reconstructs blocked state on its next run.

### Privileged helper operations

`wg-admin.py` gains two operations:

```text
setexitall <nl|us> <manual|quota>
setexitpolicy <0|1> <nl-quota-gib> <us-quota-gib>
```

`setexitpolicy` validates all values and atomically writes the policy file with
the required owner, group, and mode.

`setexitall` performs one compensating transaction:

1. Acquire the existing admin lock.
2. Load and retain the exact previous registry bytes.
3. Update every client's exit in memory, preserving absence as the NL default.
4. Atomically write the new registry.
5. Run one `exit-route.sh sync` and verify its postconditions.
6. Flush conntrack for every client whose assignment changed.
7. Append one audit entry with reason, direction, and changed-client count.

If routing application or verification fails, the helper restores the previous
registry bytes and re-syncs the previous routing state before returning an
error. If compensating rollback also fails, the response explicitly reports a
critical rollback failure; it must never claim success.

To support this contract, `exit-route.sh sync` must stop treating a missing
`wg-us` interface as success when US clients are requested. It must propagate
command failures and verify:

- when the registry contains enabled US clients, the US interface, route table,
  rule, and expected per-client mark rules exist;
- when all clients are on NL, no tagged US client mark rules remain.

The web service checks fresh egress health and target quota before calling the
helper. Helper-side structural verification is a second safety layer and does
not replace the egress check.

## API Contract

`/api/status` adds an `exit_policy` object:

```json
{
  "exit_policy": {
    "auto_switch": true,
    "exits": {
      "nl": {
        "used": 123,
        "quota": 536870912000,
        "clients": 14,
        "healthy": true,
        "exhausted": false
      },
      "us": {
        "used": 0,
        "quota": 536870912000,
        "clients": 0,
        "healthy": true,
        "exhausted": false
      }
    },
    "blocked": null,
    "last_switch": null
  }
}
```

`blocked`, when present, contains a stable code, source, target, and a
human-readable message. `last_switch`, when present, contains timestamp,
source, target, reason (`manual` or `quota`), and changed-client count.

The existing CSRF-protected `/api/admin` endpoint accepts:

```json
{"op":"setexitpolicy","auto_switch":true,"quotas_gib":{"nl":500,"us":500}}
```

```json
{"op":"setexitall","exit":"us"}
```

The HTTP layer assigns `manual` to browser bulk requests; clients cannot forge
the `quota` audit reason. Automatic actions call the same internal guarded path
with reason `quota`. Unknown fields do not expand helper arguments. Invalid
policy values return 400. A healthy/quota precondition failure returns 409 with
a stable reason code. Helper or rollback failures return an error response and
critical structured log event.

## UI Design

The NL and US monthly pills in the header become accessible buttons. Their
values come from `exit_policy.exits`, not a frontend regrouping of peers. Each
button opens an **Exit routing** modal.

The modal contains:

- one NL row and one US row;
- health state, assigned-client count, monthly used/quota text, and progress;
- whole-GiB quota inputs;
- an Auto switch toggle;
- **Switch all to NL** and **Switch all to US** actions.

Bulk actions open a confirmation step showing target, affected-client count,
and a warning that active connections will briefly reconnect. A target button
is disabled when that exit is unhealthy, its health is stale, or its quota is
exhausted, with an inline explanation.

Quota pills have three visual states, always paired with text or an accessible
label:

- normal below 90%;
- warning from 90% up to the quota;
- critical at or above the quota.

When auto switching is blocked, a persistent critical banner states the reason.
After an automatic success, the UI shows a notice such as `All clients switched
NL -> US: quota reached`. The modal, confirmation, banner, tooltips, and notices
support both existing EN and RU modes. Keyboard focus trapping, Escape handling,
reduced motion, and existing mobile behavior are preserved.

## Failure Behavior

| Condition | Result |
| --- | --- |
| Auto switch disabled | Record usage only |
| Source below quota | No action |
| Target health failed or older than 60 seconds | Keep current exit; critical blocked state; retry |
| Target quota exhausted | Keep current exit; critical blocked state; retry next month |
| Both exits exhausted | Keep current exit; no ping-pong |
| Helper rejects or routing apply fails | Roll back registry and routing; report critical error |
| Rollback fails | Report explicit rollback failure; never report success |
| Policy file missing or invalid | Auto off; 500 GiB defaults; surface configuration warning |
| Tunnel counters unavailable | Do not advance usage or auto-switch from stale data |

## Testing

Backend unit tests cover:

- NL and US delta accrual independently;
- first-sample baselines and WireGuard counter resets;
- calendar-month boundaries;
- one-time backfill and migration idempotence;
- exact `used >= quota` threshold;
- auto disabled;
- healthy, unhealthy, stale, and exhausted targets;
- all-clients registry updates, including disabled clients;
- no repeated switch or ping-pong;
- persistence across a new month without changing the current exit;
- policy file defaults, bounds, validation, and atomic writes;
- one routing sync per bulk operation;
- conntrack flushes only for changed assignments;
- registry/routing rollback and rollback-failure reporting;
- manual versus quota audit reasons;
- API CSRF, request validation, 409 preconditions, and status shape.

Frontend tests cover:

- rendering server-provided NL and US totals and configured quotas;
- normal, warning, and critical quota states;
- enabled and disabled bulk buttons with explanations;
- policy form validation and request payloads;
- confirmation copy and affected-client count;
- persistent blocked banner and automatic-switch notice;
- EN/RU labels and accessible control names.

Verification runs the full existing suite plus the new tests:

```sh
python3 -m unittest discover -s tests -q
```

Deployment continues through the existing `deploy.sh`; no new daemon or systemd
unit is introduced.

## Acceptance Criteria

- The operator can move every registered client to either healthy,
  non-exhausted exit from one modal and one confirmed action.
- The helper updates the registry and routing once, flushes changed connections,
  and records one audit event.
- Each exit displays an independent, server-calculated calendar-month total and
  configurable quota.
- With Auto switch enabled, reaching an exit quota moves the full registry to
  the healthy non-exhausted alternative without requiring an open browser.
- An unsafe target never receives clients automatically or manually.
- A failed apply restores the prior assignment and routing or reports an
  explicit critical rollback failure.
- Month rollover resets usage selection without moving clients.
- Existing per-client switching, history, authentication, CSRF, split-tunnel,
  and EN/RU behavior continue to work.

## Non-Goals

- More than two exits.
- Hosting-provider billing API integration.
- Email, push, or chat notifications.
- Time-of-day or weighted load balancing.
- Automatically returning to NL at month rollover.
- A force switch to an unhealthy or exhausted target.
