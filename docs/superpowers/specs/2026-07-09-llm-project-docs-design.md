# LLM Project Docs (AGENTS.md + Architecture)

## Goal

Give the next LLM session a fast, reliable start on this repo: what the system
is, where to look, what must not be broken, and how to verify — without dumping
full API catalogs or setup runbooks into the agent entrypoint.

## Audience

Primary: Cursor / coding agents starting a new task.
Secondary: humans who want a short architecture map (SETUP remains the
from-scratch runbook; README remains the product overview).

## Deliverables

| File | Role | Target size |
| --- | --- | --- |
| `AGENTS.md` (repo root) | Agent entrypoint: map, invariants, verify | ~80–120 lines |
| `docs/ARCHITECTURE.md` | Topology, layers, dual-exit/split, secrets | ~100–150 lines |

No new Cursor rules, no full OpenAPI-style API reference, no changelog.

## AGENTS.md contents

1. **What this is** — cascade VPN dashboard/manager on the entry node; zero
   deps / no build; Python stdlib HTTPS + vanilla JS.
2. **Read first** — links to `docs/ARCHITECTURE.md`, `README.md`, `docs/SETUP.md`.
3. **Map** — task → files table covering UI, status/read path, privileged
   writes, exit routing, split-tunnel, deploy, tests.
4. **Invariants**
   - Writes only via `wg-admin.py` through sudo; `wg-ui.py` is read-oriented.
   - Secrets and stateful data stay on the server (`/etc/wg-ui`, `/var/lib/wg-ui`),
     never in the repo.
   - Exit contract lives in `exit_model.py` (shared by admin, UI, exit-route).
   - After client mutations that affect routing, always `sync_exit_routes`
     (idempotent; do not reintroduce `was_us` / `exit=="us"` call-site branches).
   - Keep `app.js` from re-absorbing cascade/clients UI (already split).
5. **Verify** — `python3 -m unittest discover -s tests -q`; deploy with
   `./deploy.sh` (preflight + rsync `app/` + health check).
6. **Out of scope** — building the WireGuard cascade itself (keys, kill-switch,
   policy routing); the panel assumes tunnels already exist.

## ARCHITECTURE.md contents

1. **Topology** — dual-exit ASCII diagram; per-client exit chosen on entry via
   fwmark; client WireGuard config unchanged.
2. **Layers** — browser (`app.js` / `cascade.js` / `clients.js`) → `wg-ui.py`
   (HTTPS, `/api/*`) → `wg-admin.py` (root writes) → shells
   (`exit-route.sh`, `split-server.sh`) + WireGuard ifaces (`wg-cl`, `wg-do`,
   `wg-us`).
3. **Dual-exit** — `exit_model` → `clients.json` → `exit-route.sh` (mark `0x65`,
   table 65 → `wg-us`); NL is the unmarked default; status exposes
   `tunnel.state` + `tunnel.exits` (no legacy flat NL-only tunnel fields).
4. **Split-tunnel** — global RU-direct on the entry node (`split-server.sh` /
   ipset); orthogonal to per-client exit.
5. **Data & secrets** — short path table (same ownership story as README/SETUP).
6. **Deploy shape** — `deploy.sh` ships only `app/`; systemd units under
   `deploy/` are installed manually (see SETUP).

## Non-goals

- Documenting every admin op and JSON field.
- Replacing SETUP or README.
- Encoding review nits beyond the invariants above.

## Success criteria

- A new agent can answer “where do I change X?” and “what must I not break?”
  from `AGENTS.md` + one hop into `ARCHITECTURE.md`.
- Docs stay short enough to load cheaply at session start.
- Links between README / SETUP / AGENTS / ARCHITECTURE are consistent.

## Implementation notes

Write the two markdown files to match this outline; add a one-line pointer from
`README.md` to `AGENTS.md` / `ARCHITECTURE.md` if it helps discovery without
duplicating content. Commit docs only (no code changes required).
