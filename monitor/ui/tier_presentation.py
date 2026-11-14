"""Safe, cache-only display model for ENABLED Monitor collateral tiers."""

from __future__ import annotations

from typing import Any


TIERS = ("T1", "T2", "T3", "T4", "unknown")


def _verified_counts(raw: Any) -> dict[str, int] | None:
    if not isinstance(raw, dict):
        return None
    counts: dict[str, int] = {}
    for tier in TIERS:
        count = raw.get(tier)
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            return None
        counts[tier] = count
    return counts


def build_tier_display(public_summary: dict[str, Any]) -> dict[str, Any]:
    """Show ENABLED nodes only; never substitute global or partial tier counts."""
    tiers = public_summary.get("masternode_tiers") or {}
    total = public_summary.get("masternode_total")
    enabled = public_summary.get("masternode_enabled")
    all_counts = _verified_counts(tiers.get("counts"))
    enabled_counts = _verified_counts(tiers.get("enabled_counts"))
    valid = (
        tiers.get("available") is True
        and tiers.get("enabled_available") is True
        and isinstance(total, int) and not isinstance(total, bool) and total > 0
        and isinstance(enabled, int) and not isinstance(enabled, bool)
        and 0 <= enabled <= total
        and all_counts is not None and sum(all_counts.values()) == total
        and enabled_counts is not None and sum(enabled_counts.values()) == enabled
        and all(enabled_counts[tier] <= all_counts[tier] for tier in TIERS)
    )
    if not valid:
        return {
            "counts": {tier: "-" for tier in TIERS},
            "show_unknown": False,
            "label": "ENABLED tier snapshot unavailable",
            "available": False,
        }

    source = "Explorer cache" if tiers.get("source") == "explorer_cache" else "Core RPC"
    freshness = "stale" if tiers.get("stale") else "latest"
    return {
        "counts": enabled_counts,
        "show_unknown": enabled_counts["unknown"] > 0,
        "label": f"{source} · {freshness}",
        "available": True,
    }
