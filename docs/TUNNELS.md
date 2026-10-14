# Cascade tunnels (entry ↔ exit) on AmneziaWG

The client leg (`wg-cl`, device → entry) is plain WireGuard. The two cascade legs
— `wg-do` (entry → NL exit) and `wg-us` (entry → US exit) — run on
[AmneziaWG](https://github.com/amnezia-vpn/amneziawg-linux-kernel-module): a
WireGuard fork whose handshake is padded and disguised, so DPI that fingerprints
plain WireGuard between the entry and an exit does not recognise it. Interface
names stay `wg-do` / `wg-us`, so routing (`exit-route.sh`, `split-server.sh`,
table 200 / 65) is unchanged; only the tool that reads them differs.

Templates (placeholders only, never deployed automatically):

| File | Goes to |
| --- | --- |
| `deploy/tunnels/wg-do.conf.example` | entry: `/etc/amnezia/amneziawg/wg-do.conf` |
| `deploy/tunnels/wg-us.conf.example` | entry: `/etc/amnezia/amneziawg/wg-us.conf` |
| `deploy/tunnels/awg0.conf.example`  | each exit: `/etc/amnezia/amneziawg/awg0.conf` |

## What lives outside this repo

| Where | What | Delivered by |
| --- | --- | --- |
| entry `/etc/amnezia/amneziawg/*.conf`, `/etc/wireguard/wg-cl.conf` | tunnel keys + obfuscation values | by hand (this doc) |
| exit `/etc/amnezia/amneziawg/awg0.conf` | exit side of each tunnel | by hand (this doc) |
| entry `/etc/wg-ui/wg-ui.env`, cert, `clients.json` | panel secrets + registry | by hand (`docs/SETUP.md`) |
| entry `/etc/sudoers.d/wg-ui` | exact read + helper commands | **`deploy.sh`** from `deploy/sudoers.wgui` |
| entry `/etc/systemd/system/wg-*.service` | panel / split / exit-route units | **`deploy.sh`** from `deploy/*.service` |
| provider | NL/US droplets, US Reserved IP | provider console |

`deploy.sh` installs a changed sudoers file only after `visudo -cf`, installs
changed units with a backup and `daemon-reload`, but never enables or restarts
the split / exit-route units — that would flap routing. Restart them yourself
when their unit changed. `--skip-config` ships code only.

## Bring up one leg (example: entry → NL)

1. **Install AmneziaWG on both ends** (Ubuntu 24.04; DKMS builds the module):

   ```sh
   add-apt-repository -y ppa:amnezia/ppa
   apt-get install -y amneziawg        # needs linux-headers-$(uname -r)
   modprobe amneziawg && awg --version
   ```

2. **Keys** — one pair per end per tunnel, kept on that host:

   ```sh
   cd /etc/amnezia/amneziawg && umask 077
   awg genkey > nl.key && awg pubkey < nl.key       # on the exit
   awg genkey > do.key && awg pubkey < do.key       # on the entry
   ```

3. **Obfuscation values** — generate once per tunnel and put the *same* `Jc,
   Jmin, Jmax, S1, S2, H1..H4` on both ends: `S1`,`S2` in 15..150 with
   `S1 + 56 != S2`; `H1..H4` four distinct random integers above 4. Use a
   different set for `wg-us`.

4. **Exit**: fill `awg0.conf` from the template (new UDP port, its own /24 —
   `10.21.0.0/24` for NL, `10.31.0.0/24` for US), then
   `systemctl enable --now awg-quick@awg0`.

5. **Entry, tested side by side first**: bring the new leg up under a temporary
   name with `Table = off` and no PostUp hooks, and check it before touching live
   traffic:

   ```sh
   awg-quick up awg-test
   awg show awg-test latest-handshakes                 # non-zero timestamp
   curl -s --interface awg-test https://ifconfig.me    # = the exit's egress IP
   awg-quick down awg-test
   ```

6. **Cut over** (seconds of client downtime for `wg-do`; auto-rollback if the
   new leg doesn't come up):

   ```sh
   systemctl stop wg-quick@wg-do && systemctl start awg-quick@wg-do
   # verify handshake + egress, else: systemctl stop awg-quick@wg-do; systemctl start wg-quick@wg-do
   systemctl disable wg-quick@wg-do && systemctl enable awg-quick@wg-do
   ```

   For `wg-us` follow with `systemctl restart wg-exit-route` (the table-65 route
   dies with the old interface).

7. **Panel**: add the leg to `WGUI_AWG_IFACES` in `/etc/wg-ui/wg-ui.env`
   (`WGUI_AWG_IFACES=wg-do wg-us`) and redeploy — `deploy/sudoers.wgui` already
   allows `awg show wg-do|wg-us dump`.

Check the RPDB afterwards — the order must be exactly:

```
1000:   from all fwmark 0x64 lookup main     # RU-direct split
1100:   from all fwmark 0x65 lookup 65       # US clients
32765:  from 10.10.0.0/24 lookup 200         # everyone else → NL
```

If `from 10.10.0.0/24 lookup 200` shows up with a priority *below* 1000, the
`wg-do` config lacks the pinned `priority 32765` and is overriding split and US.

## Reserved IP for an exit

An exit's provider IP can get blocked on the path from the entry (seen
2026-10-14: every packet entry → US exit IP dropped in transit while the droplet
itself was healthy). Point the entry at a provider **Reserved IP** instead of the
droplet's own address:

1. Provider console → Networking → Reserved IPs → assign one to the exit droplet
   (free while assigned). On DigitalOcean the droplet sees inbound traffic on its
   anchor address; replies leave fine and egress keeps the droplet's own IP.
2. From the entry, confirm it is reachable (`timeout 4 bash -c '</dev/tcp/<rip>/22'`).
3. Set `Endpoint = <reserved-ip>:<port>` in the entry's `wg-us.conf` (or
   `wg-do.conf`) and restart that leg.

If the Reserved IP is blocked later, assign a new one and change only that
`Endpoint` line. The panel's expected-egress setting (`WGUI_US_EXIT_IP`) is the
exit's *egress* address, not the endpoint — it does not change.
