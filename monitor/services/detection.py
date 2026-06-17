from __future__ import annotations

import time
from typing import Any

from monitor.services.aggregation import build_peer_version_summary


SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}
FORK_WARNING_BLOCKS = 720
FORK_CRITICAL_BLOCKS = 180
SITE_FAILURE_ALERT_THRESHOLD = 2


def build_alert(
    alert_type: str,
    severity: str,
    title: str,
    message: str,
    *,
    source: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    details = details or {}
    identity = details.get("id_suffix", "")
    alert_id = f"{alert_type}:{source}:{identity}".rstrip(":")
    return {
        "id": alert_id,
        "type": alert_type,
        "severity": severity,
        "title": title,
        "message": message,
        "source": source,
        "details": details,
    }


def determine_fork_state(current_height: int | None, fork_height: int | None) -> str:
    if current_height is None:
        return "ERROR"
    if fork_height is None:
        return "POST_FORK"
    if current_height < fork_height:
        return "PRE_FORK"
    if current_height == fork_height:
        return "ACTIVATING"
    return "POST_FORK"


def evaluate_fork_state(
    recent_blocks: list[dict[str, Any]],
    current_height: int | None,
    fork_height: int | None,
    *,
    upgrade_ratio: float,
    target_version: str,
    fork_configured: bool,
    eta_seconds: int | None = None,
    last_block_age: int | None = None,
    block_target_seconds: int = 60,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    state = determine_fork_state(current_height, fork_height)
    suspicious_blocks = [block for block in recent_blocks if fork_height is not None and block["height"] < fork_height and block["has_hoohash_bit"]]
    invalid_blocks = [block for block in recent_blocks if block["has_hoohash_bit"] and block["has_xelis_bit"]]
    activation_blocks = [block for block in recent_blocks if fork_height is not None and block["height"] >= fork_height and block["has_hoohash_bit"]]
    activation_seen = bool(activation_blocks)

    alerts: list[dict[str, Any]] = []
    # The fork is long past activation for the public monitor. Missing legacy fork
    # parameters should not dominate the live health view as a critical alert.

    for block in suspicious_blocks:
        alerts.append(
            build_alert(
                "pre_fork_activation_attempt",
                "critical",
                "Pre-fork activation attempt detected",
                f"Block {block['height']} signaled the Hoohash bit before the configured fork height.",
                source="rpc_local",
                details={"height": block["height"], "id_suffix": str(block["height"])},
            )
        )

    if last_block_age is None:
        chain_moving_status = "unknown"
    elif last_block_age <= block_target_seconds * 3:
        chain_moving_status = "healthy"
    elif last_block_age <= block_target_seconds * 8:
        chain_moving_status = "slow"
    else:
        chain_moving_status = "stalled"

    countdown_blocks = max((fork_height or 0) - (current_height or 0), 0) if fork_height is not None and current_height is not None else None
    readiness_level, readiness_reasons = _evaluate_fork_readiness(state, countdown_blocks)
    stall_level = _evaluate_fork_stall_level(
        state,
        countdown_blocks,
        last_block_age,
        block_target_seconds,
    )
    fork_status = {
        "fork_height": fork_height,
        "current_height": current_height,
        "blocks_after_fork": max(current_height - fork_height, 0) if current_height is not None and fork_height is not None else 0,
        "chain_moving_status": chain_moving_status,
        "countdown_blocks": countdown_blocks,
        "blocks_remaining": countdown_blocks,
        "remaining_blocks": countdown_blocks,
        "estimated_eta_seconds": eta_seconds,
        "state": state,
        "hoohash_bit": None,
        "xelis_bit": None,
        "upgrade_ratio": round(upgrade_ratio, 4),
        "target_version": target_version,
        "activation_seen": activation_seen,
        "activation_height_seen": activation_blocks[0]["height"] if activation_blocks else None,
        "readiness_level": readiness_level,
        "readiness_reasons": readiness_reasons,
        "stall_level": stall_level,
        "last_block_age": last_block_age,
        "suspicious_blocks": suspicious_blocks[-10:],
        "invalid_version_blocks": invalid_blocks[-10:],
    }
    return fork_status, alerts


def _evaluate_fork_readiness(state: str, countdown_blocks: int | None) -> tuple[str, list[str]]:
    if countdown_blocks is None:
        if state == "POST_FORK":
            return "normal", ["Network is already post-upgrade; legacy fork countdown is no longer relevant."]
        return "normal", []

    reasons: list[str] = []
    if state == "PRE_FORK":
        if countdown_blocks <= FORK_CRITICAL_BLOCKS:
            reasons.append(f"Fork height within {FORK_CRITICAL_BLOCKS} blocks.")
            return "critical", reasons
        if countdown_blocks <= FORK_WARNING_BLOCKS:
            reasons.append(f"Fork height within {FORK_WARNING_BLOCKS} blocks.")
            return "warning", reasons
    elif state == "ACTIVATING":
        reasons.append("Fork activation window is active.")
        return "critical", reasons
    elif state == "POST_FORK":
        reasons.append("Hoohash upgrade is active on the monitored chain.")
        return "normal", reasons

    return "normal", reasons


def _evaluate_fork_stall_level(
    state: str,
    countdown_blocks: int | None,
    last_block_age: int | None,
    block_target_seconds: int,
) -> str:
    if last_block_age is None or block_target_seconds <= 0:
        return "normal"

    in_alert_window = state in {"ACTIVATING", "POST_FORK"} or (
        state == "PRE_FORK" and countdown_blocks is not None and countdown_blocks <= FORK_WARNING_BLOCKS
    )
    if not in_alert_window:
        return "normal"

    if last_block_age > block_target_seconds * 12:
        return "critical"
    if last_block_age > block_target_seconds * 8:
        return "warning"
    return "normal"


def detect_no_new_block_alert(
    recent_blocks: list[dict[str, Any]],
    *,
    current_timestamp: int | None,
    block_target_seconds: int,
) -> list[dict[str, Any]]:
    if not recent_blocks:
        return []
    latest_block = recent_blocks[-1]
    latest_time = int(latest_block["time"])
    now = current_timestamp or int(time.time())
    age = now - latest_time

    if age > block_target_seconds * 12:
        return [
            build_alert(
                "stalled_blocks",
                "critical",
                "No recent block",
                f"No new block has been seen for {age} seconds.",
                source="rpc_local",
                details={"age_seconds": age},
            )
        ]
    if age > block_target_seconds * 5:
        return [
            build_alert(
                "slow_blocks",
                "warning",
                "Last block age elevated",
                f"Last block age is {age} seconds. This can happen during normal PEPEPOW RPC lag; monitor for persistence.",
                source="rpc_local",
                details={"age_seconds": age},
            )
        ]
    return []


def detect_mempool_alert(
    *,
    mempool_txs: int | None,
    mempool_zero_duration: int,
    zero_window_has_new_blocks: bool,
) -> list[dict[str, Any]]:
    if mempool_txs != 0 or mempool_zero_duration <= 600 or not zero_window_has_new_blocks:
        return []
    return [
        build_alert(
            "mempool_zero",
            "warning",
            "Mempool empty while blocks advance",
            f"Mempool has been empty for {mempool_zero_duration} seconds while new blocks were still arriving.",
            source="public_api_remote",
            details={"duration_seconds": mempool_zero_duration},
        )
    ]


def detect_rpc_health_alert(
    *,
    rpc_local_status: str,
    cooldown_active_seconds: int,
) -> list[dict[str, Any]]:
    if rpc_local_status != "cooldown" or cooldown_active_seconds <= 300:
        return []
    return [
        build_alert(
            "rpc_cooldown_too_long",
            "warning",
            "RPC cooldown active",
            f"Local RPC has remained in cooldown for {cooldown_active_seconds} seconds.",
            source="rpc_local",
            details={"cooldown_active_seconds": cooldown_active_seconds},
        )
    ]


def detect_upgrade_ratio_alert(
    *,
    countdown_blocks: int | None,
    upgrade_ratio: float,
    target_version: str,
) -> list[dict[str, Any]]:
    if countdown_blocks is None or countdown_blocks > 500 or upgrade_ratio >= 0.80:
        return []
    percent = round(upgrade_ratio * 100, 2)
    return [
        build_alert(
            "low_upgrade_ratio_near_fork",
            "critical",
            "Low upgrade ratio near fork",
            f"Only {percent}% of enabled masternodes appear upgraded to {target_version} within {countdown_blocks} blocks of the fork.",
            source="monitor",
            details={"countdown_blocks": countdown_blocks, "upgrade_ratio": round(upgrade_ratio, 4)},
        )
    ]


def detect_fork_readiness_alert(fork_status: dict[str, Any]) -> list[dict[str, Any]]:
    level = str(fork_status.get("readiness_level") or "normal")
    if level not in {"warning", "critical"}:
        return []

    remaining_blocks = fork_status.get("remaining_blocks")
    title = "Fork approaching" if level == "warning" else "Fork imminent"
    message = (
        f"Fork height is {remaining_blocks} blocks away."
        if remaining_blocks is not None
        else "Fork activation window is active."
    )
    return [
        build_alert(
            "fork_readiness",
            level,
            title,
            message,
            source="monitor",
            details={
                "remaining_blocks": remaining_blocks,
                "state": fork_status.get("state"),
            },
        )
    ]


def detect_fork_stall_alert(fork_status: dict[str, Any]) -> list[dict[str, Any]]:
    level = str(fork_status.get("stall_level") or "normal")
    if level not in {"warning", "critical"}:
        return []

    last_block_age = fork_status.get("last_block_age")
    return [
        build_alert(
            "fork_stall",
            level,
            "Chain may be stalled",
            f"Last block age is {last_block_age} seconds. This threshold is relaxed for normal PEPEPOW RPC lag.",
            source="rpc_local",
            details={
                "last_block_age": last_block_age,
                "state": fork_status.get("state"),
                "remaining_blocks": fork_status.get("remaining_blocks"),
            },
        )
    ]


def detect_mempool_zero_alert(mempool_txs: int | None, recent_blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if mempool_txs != 0 or len(recent_blocks) < 5:
        return []
    return [
        build_alert(
            "mempool_zero_recent",
            "warning",
            "Mempool empty while blocks continue",
            "The mempool is empty even though recent blocks are being produced.",
            source="public_api_remote",
            details={"recent_blocks": len(recent_blocks)},
        )
    ]


def detect_site_health_alerts(public_sites: list[dict[str, Any]]) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    for site in public_sites:
        status = site.get("status")
        failures = int(site.get("consecutive_failures", 0) or 0)
        if status == "down" and failures >= SITE_FAILURE_ALERT_THRESHOLD:
            alerts.append(
                build_alert(
                    "public_site_down",
                    "warning",
                    "Public service unavailable",
                    f"{site.get('name') or site.get('url')} has failed {failures} consecutive checks.",
                    source="site_status",
                    details={"id_suffix": str(site.get("name") or site.get("url")), "failures": failures},
                )
            )
    return alerts


def detect_source_degraded_alert(source_health: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    for name, status in source_health.items():
        if status.get("status") in {"down", "cooldown"}:
            alerts.append(
                build_alert(
                    "source_down",
                    "warning",
                    "Data source unavailable",
                    f"{name} is {status.get('status')}: {status.get('last_error') or 'no recent successful check'}.",
                    source=name,
                    details={"id_suffix": name},
                )
            )
    return alerts


def sort_alerts(alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(alerts, key=lambda item: (SEVERITY_ORDER.get(item.get("severity"), 99), item.get("type", "")))


def summarize_peers(peerinfo: list[dict[str, Any]], min_upgraded_subver: str | None) -> dict[str, Any]:
    versions = build_peer_version_summary(peerinfo, min_upgraded_subver)
    return {
        "total_peers": len(peerinfo),
        "upgraded_peers": sum(item["count"] for item in versions if item["is_upgraded"] is True),
        "legacy_peers": sum(item["count"] for item in versions if item["is_upgraded"] is False),
        "unknown_peers": sum(item["count"] for item in versions if item["is_upgraded"] is None),
        "versions": versions,
    }
