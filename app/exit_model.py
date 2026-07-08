"""Canonical per-client exit contract (NL default / US via fwmark).

Shared by wg-admin.py, wg-ui.py, and exit-route.sh so validation and
defaulting stay in one place.
"""
EXITS = ("nl", "us")  # nl = default via wg-do; us = mark → wg-us


def normalize_exit(val):
    """Strict write-path validation. Raises ValueError on unknown exit."""
    e = (val or "nl").strip().lower()
    if e not in EXITS:
        raise ValueError("exit must be nl or us")
    return e


def client_exit(c):
    """Read-path normalize: missing/unknown → nl (default route)."""
    e = (c or {}).get("exit", "nl")
    return e if e in EXITS else "nl"
