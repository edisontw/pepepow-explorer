"""Safe, cache-only display model for the Monitor collateral tier widget."""

from __future__ import annotations

from typing import Any


TIERS = ("T1", "T2", "T3", "T4", "unknown")


def build_tier_display(public_summary: dict[str, Any]) -> dict[str, Any]:
    """Never label partial counts as the complete Core masternode roster."""
    tiers = public_summary.get("masternode_tiers") or {}
    raw_counts = tiers.get("counts") or {}
    expected = public_summary.get("masternode_total")
    counts: dict[str, int] = {}
    valid = bool(tiers.get("available")) and isinstance(raw_counts, dict)
    for name in TIERS:
        value = raw_counts.get(name) if isinstance(raw_counts, dict) else None
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            counts[name] = value
        else:
            valid = False

    # Never render 56 Explorer nodes as "all known" when Core says 311.
    valid = (
        valid
        and isinstance(expected, int)
        and not isinstance(expected, bool)
        and expected > 0
        and sum(counts.values()) == expected
    )
    if not valid:
        return {
            "counts": {name: "-" for name in TIERS},
            "show_unknown": False,
            "label": "Tier snapshot unavailable",
            "available": False,
        }

    source = "Explorer cache" if tiers.get("source") == "explorer_cache" else "Core RPC"
    freshness = "stale" if tiers.get("stale") else "latest"
    return {
        "counts": counts,
        "show_unknown": counts["unknown"] > 0,
        "label": f"{source} · {freshness}",
        "available": True,
    }
