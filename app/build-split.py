#!/usr/bin/env python3
"""Build the split-tunnel AllowedIPs (everything-except RU+LAN+extras) for clients
that route RU directly. Sources:
  - aggregated RU IPv4 zone (cached; re-download with --refresh)
  - /etc/wg-ui/split-extra.txt  (user extras: CIDR / IP / domain, one per line)
  - private / LAN ranges (always direct)
Writes /etc/wg-ui/split-allowedips.txt (comma CIDRs) + /etc/wg-ui/split-meta.json.
Run by wg-admin.py (as root). Re-runnable."""
import sys, os, socket, json, time, ipaddress, tempfile, urllib.request

RU_URL   = "https://www.ipdeny.com/ipblocks/data/aggregated/ru-aggregated.zone"
DIR      = "/etc/wg-ui"
RU_CACHE = DIR + "/ru-zone.cache"
EXTRA    = DIR + "/split-extra.txt"
OUT      = DIR + "/split-allowedips.txt"     # complement (client-side AllowedIPs)
DIRECT   = DIR + "/split-direct.txt"          # RU + extras as plain CIDRs (server-side ipset)
META     = DIR + "/split-meta.json"
PRIVATE  = ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "169.254.0.0/16"]

def w_atomic(path, data, mode=0o644):
    fd, tmp = tempfile.mkstemp(dir=DIR)
    os.write(fd, data.encode()); os.close(fd); os.chmod(tmp, mode); os.replace(tmp, path)

def download_ru():
    req = urllib.request.Request(RU_URL, headers={"User-Agent": "wg-ui-split/1"})
    data = urllib.request.urlopen(req, timeout=30).read().decode()
    good = []
    for line in data.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            try:
                if ipaddress.ip_network(line).version == 4:
                    good.append(line)
            except ValueError:
                pass
    if len(good) < 1000:
        raise RuntimeError("RU zone too small (%d)" % len(good))
    w_atomic(RU_CACHE, "\n".join(good))
    return good

def load_ru(refresh):
    if refresh or not os.path.exists(RU_CACHE):
        return download_ru()
    with open(RU_CACHE) as f:
        return [l.strip() for l in f if l.strip()]

def load_extra():
    items = []
    try:
        with open(EXTRA) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    items.append(line)
    except FileNotFoundError:
        pass
    return items

def parse_entry(entry):
    """CIDR / IP / domain -> list of v4 ip_networks (domain resolved at build time)."""
    try:
        n = ipaddress.ip_network(entry, strict=False)
        return [n] if n.version == 4 else []
    except ValueError:
        pass
    out = []
    try:
        for info in socket.getaddrinfo(entry, None, socket.AF_INET):
            out.append(ipaddress.ip_network(info[4][0] + "/32"))
    except Exception:
        pass
    return list(set(out))

def complement(exclude):
    ex = sorted(ipaddress.collapse_addresses(exclude), key=lambda n: int(n.network_address))
    res, cur, end = [], 0, 2 ** 32 - 1
    for n in ex:
        s, e = int(n.network_address), int(n.broadcast_address)
        if s > cur:
            res += ipaddress.summarize_address_range(ipaddress.IPv4Address(cur), ipaddress.IPv4Address(s - 1))
        cur = max(cur, e + 1)
    if cur <= end:
        res += ipaddress.summarize_address_range(ipaddress.IPv4Address(cur), ipaddress.IPv4Address(end))
    return res

def main():
    refresh = "--refresh" in sys.argv
    ru = load_ru(refresh)
    ru_nets = [ipaddress.ip_network(c) for c in ru]
    extra_items = load_extra()
    extra_nets = []
    for it in extra_items:
        extra_nets += parse_entry(it)
    excl = ru_nets + extra_nets + [ipaddress.ip_network(x) for x in PRIVATE]
    comp = complement(excl)
    allowed = ", ".join(str(n) for n in comp)
    w_atomic(OUT, allowed)
    # server-side: the DIRECT set (RU + extras, no private — client LAN isn't routed via VDSina)
    direct = list(ipaddress.collapse_addresses(ru_nets + extra_nets))
    w_atomic(DIRECT, "\n".join(str(n) for n in direct))
    meta = {"ru_count": len(ru_nets), "extra": extra_items, "extra_resolved": len(extra_nets),
            "complement_count": len(comp), "direct_count": len(direct), "bytes": len(allowed),
            "built_at": time.strftime("%Y-%m-%d %H:%M"), "refreshed": bool(refresh)}
    w_atomic(META, json.dumps(meta))
    print(json.dumps(meta))

if __name__ == "__main__":
    main()
