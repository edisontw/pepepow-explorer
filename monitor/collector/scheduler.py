from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from monitor.cache.base import CacheBackend
from monitor.collector.normalize import block_to_sample
from monitor.collector.sources import MonitorSources
from monitor.config import ComparisonSource, Settings
from monitor.services.aggregation import (
    average,
    build_hashrate_point,
    build_interval_points,
    build_masternode_summary,
    build_masternode_summary_fingerprint,
    format_hashrate,
    is_enabled_masternode,
    is_probable_ip_semver_noise,
    sanitize_peers,
)
from monitor.services.masternodes import merge_masternode_records, normalize_masternode_items
from monitor.services.detection import (
    build_alert,
    detect_fork_readiness_alert,
    detect_fork_stall_alert,
    detect_mempool_alert,
    detect_no_new_block_alert,
    detect_rpc_health_alert,
    detect_site_health_alerts,
    detect_source_degraded_alert,
    detect_upgrade_ratio_alert,
    evaluate_fork_state,
    sort_alerts,
    summarize_peers,
)


class MonitorCollector:
    _MASTERNODES_CACHE_KEY = "monitor:masternodes:latest"
    _SITE_STATUS_CACHE_KEY = "monitor:sites:latest"
    _POOL_STATUS_CACHE_KEY = "monitor:pools:latest"

    def __init__(
        self,
        settings: Settings,
        cache: CacheBackend,
        sources: MonitorSources,
        logger: logging.Logger,
    ) -> None:
        self.settings = settings
        self.cache = cache
        self.sources = sources
        self.logger = logger
        self._task: asyncio.Task | None = None
        self._refresh_task: asyncio.Task | None = None
        self._refresh_lock = asyncio.Lock()
        self._source_health: dict[str, dict[str, Any]] = {}
        self._split_state: dict[str, dict[str, Any]] = {}
        self._active_alerts: dict[str, dict[str, Any]] = {}
        self._latest_snapshot: dict[str, Any] = self._empty_snapshot()
        self._last_probe_at: dict[str, float] = {}
        self._rpc_fail_count = 0
        self._last_success_timestamp: str | None = None
        self._rpc_cooldown_until = 0.0
        self._rpc_cooldown_started_at = 0.0
        self._probe_success_streak = 0
        self._probe_only_mode = False
        self._rpc_cycle_used = False

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run_loop(), name="monitor-collector")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._refresh_task is not None:
            self._refresh_task.cancel()
            try:
                await self._refresh_task
            except asyncio.CancelledError:
                pass
            self._refresh_task = None
        await self.sources.close()

    async def _run_loop(self) -> None:
        next_tick = time.monotonic()
        while True:
            wait_for = max(0.0, next_tick - time.monotonic())
            if wait_for:
                await asyncio.sleep(wait_for)
            next_tick += self.settings.poll_interval_seconds

            if self._refresh_lock.locked() or (self._refresh_task is not None and not self._refresh_task.done()):
                self.logger.info("refresh skipped: previous cycle still running")
                continue

            self._refresh_task = asyncio.create_task(self.refresh_once(), name="monitor-collector-refresh")

    async def refresh_once(self) -> None:
        async with self._refresh_lock:
            try:
                await self._refresh_once_unlocked()
            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger.exception("monitor collector refresh failed")
                return

    async def _refresh_once_unlocked(self) -> None:
        generated_at_dt = datetime.now(timezone.utc)
        generated_at = generated_at_dt.isoformat()
        generated_at_unix = int(generated_at_dt.timestamp())
        now_monotonic = time.monotonic()
        cycle_started = time.perf_counter()
        self._rpc_cycle_used = False

        previous_snapshot = self.cache.get_json("monitor:latest", self._latest_snapshot)

        tier_a_due = self._should_poll("tier_a", self.settings.rpc_blockcount_poll_interval_seconds, now_monotonic)
        tier_b_due = self._should_poll("tier_b", self.settings.masternode_interval_seconds, now_monotonic)
        peerinfo_due = self._should_poll("peerinfo", self.settings.peerinfo_interval_seconds, now_monotonic)
        hashrate_due = self._should_poll("hashrate", self.settings.hashrate_poll_interval_seconds, now_monotonic)
        site_status_due = self._should_poll("site_status", self.settings.site_status_interval_seconds, now_monotonic)
        mining_pools_due = self._should_poll("mining_pools", self.settings.mining_pool_interval_seconds, now_monotonic)
        probe_due = self._probe_only_mode and now_monotonic >= self._rpc_cooldown_until

        rpc_height = previous_snapshot.get("rpc_height")
        explorer_height = previous_snapshot.get("explorer_height")
        public_height = previous_snapshot.get("public_height")
        public_mempool = previous_snapshot.get("_public_mempool")
        recent_blocks = previous_snapshot.get("recent_blocks", [])
        peers_raw = previous_snapshot.get("_peerinfo_raw", [])
        peer_summary = previous_snapshot.get("peers", {}).get("summary", {})
        peer_items = previous_snapshot.get("peers", {}).get("items", [])
        peer_count = int(previous_snapshot.get("peer_count", 0) or 0)
        hashrate_hps = previous_snapshot.get("hashrate_hps")
        public_sites = list(previous_snapshot.get("services", {}).get("public_sites", []))
        mining_pools = list(previous_snapshot.get("services", {}).get("mining_pools", []))
        mining_pool_summary = dict(previous_snapshot.get("services", {}).get("mining_pool_summary", {}))
        site_checks_generated_at = previous_snapshot.get("_site_checks_generated_at")
        site_checks_generated_at_unix = previous_snapshot.get("_site_checks_generated_at_unix")
        masternode_cache_generated_at = previous_snapshot.get("_masternode_cache_generated_at")
        masternode_cache_generated_at_unix = previous_snapshot.get("_masternode_cache_generated_at_unix")
        masternode_summary_fingerprint = previous_snapshot.get("_masternode_summary_fingerprint")
        masternode_summary = {
            "enabled": int(previous_snapshot.get("masternode_enabled", 0) or 0),
            "total": int(previous_snapshot.get("masternode_total", 0) or 0),
            "upgraded_enabled": int(previous_snapshot.get("masternode_upgraded_enabled", 0) or 0),
            "legacy_enabled": int(previous_snapshot.get("masternode_legacy_enabled", 0) or 0),
            "unknown_enabled": int(previous_snapshot.get("masternode_unknown_enabled", 0) or 0),
            "upgrade_ratio": float(previous_snapshot.get("upgrade_ratio", 0.0) or 0.0),
            "versions": self._coerce_masternode_versions(previous_snapshot.get("masternode_versions", [])),
        }

        if tier_a_due or probe_due:
            rpc_height = await self._fetch_rpc_height(previous_snapshot)
            if tier_a_due:
                explorer_height, public_height, public_mempool = await asyncio.gather(
                    self._source_call("explorer_local", "explorer", self.sources.explorer_get_blockcount),
                    self._source_call("public_api_remote", "public_api", self.sources.public_get_height),
                    self._source_call("public_api_remote", "public_api", self.sources.public_get_mempool),
                )

        authoritative_height = self._pick_height(rpc_height, explorer_height, public_height, previous_snapshot.get("height"))
        height_source = self._pick_height_source(rpc_height, explorer_height, public_height, previous_snapshot.get("height_source"))

        if tier_a_due and rpc_height is not None and height_source == "rpc_local" and not self._probe_only_mode:
            recent_blocks = await self._refresh_recent_blocks(rpc_height, recent_blocks)
        else:
            recent_blocks = list(recent_blocks)[-self.settings.recent_block_window :]

        latest_block = recent_blocks[-1] if recent_blocks else None
        local_hash = latest_block["hash"] if latest_block and latest_block["height"] == authoritative_height else None

        difficulty = latest_block["difficulty"] if latest_block else previous_snapshot.get("difficulty")
        if difficulty is None and tier_a_due:
            difficulty = await self._source_call("explorer_local", "explorer", self.sources.explorer_get_difficulty)

        if peerinfo_due and not self._probe_only_mode:
            peerinfo_result = await self._source_call("rpc_local", "rpc", self.sources.rpc_get_peerinfo, rpc_operation="getpeerinfo")
            if peerinfo_result is not None:
                peers_raw = peerinfo_result
                peer_summary = summarize_peers(peerinfo_result, self.settings.min_upgraded_subver)
                peer_items = sanitize_peers(peerinfo_result)
                peer_count = len(peerinfo_result)

        if hashrate_due and not self._probe_only_mode:
            hashrate_result = await self._source_call("rpc_local", "rpc", self.sources.rpc_get_networkhashps, rpc_operation="getnetworkhashps")
            if hashrate_result is not None:
                hashrate_hps = hashrate_result

        if tier_b_due:
            (
                masternode_summary,
                masternode_summary_fingerprint,
                masternode_cache_generated_at,
                masternode_cache_generated_at_unix,
            ) = await self._collect_masternode_summary(
                peers_raw,
                masternode_summary,
                previous_fingerprint=masternode_summary_fingerprint,
                previous_generated_at=masternode_cache_generated_at,
                previous_generated_at_unix=masternode_cache_generated_at_unix,
                generated_at=generated_at,
                generated_at_unix=generated_at_unix,
            )

        if site_status_due:
            public_sites, site_checks_generated_at, site_checks_generated_at_unix = await self._collect_site_status(
                public_sites,
                generated_at,
                generated_at_unix,
            )
            self.cache.set_json(
                self._SITE_STATUS_CACHE_KEY,
                {
                    "generated_at": site_checks_generated_at,
                    "generated_at_unix": site_checks_generated_at_unix,
                    "items": public_sites,
                },
            )

        if mining_pools_due:
            mining_pools, mining_pool_summary = await self._collect_mining_pool_status(
                mining_pools,
                generated_at,
                generated_at_unix,
            )
            self.cache.set_json(
                self._POOL_STATUS_CACHE_KEY,
                {
                    "generated_at": generated_at,
                    "generated_at_unix": generated_at_unix,
                    "summary": mining_pool_summary,
                    "items": mining_pools,
                },
            )

        avg_block_time_8m, avg_block_time_30m, avg_block_time_2h, last_block_age = self._calculate_block_timing(recent_blocks, generated_at_unix)
        eta_basis = avg_block_time_8m or avg_block_time_30m or float(self.settings.block_target_seconds)
        countdown_blocks = None
        if self.settings.fork_height is not None and authoritative_height is not None:
            countdown_blocks = max(self.settings.fork_height - authoritative_height, 0)
        eta_seconds = int(round((countdown_blocks or 0) * eta_basis)) if countdown_blocks is not None else None

        fork_status, fork_alerts = evaluate_fork_state(
            recent_blocks,
            authoritative_height,
            self.settings.fork_height,
            upgrade_ratio=masternode_summary["upgrade_ratio"],
            target_version=self.settings.target_version,
            fork_configured=self.settings.fork_configured,
            eta_seconds=eta_seconds,
            last_block_age=last_block_age,
            block_target_seconds=self.settings.block_target_seconds,
        )
        fork_status["hoohash_bit"] = self.settings.hoohash_bit
        fork_status["xelis_bit"] = self.settings.xelis_bit

        comparison_results = previous_snapshot.get("comparison_results", [])
        if tier_a_due:
            comparison_results = await self._collect_comparison_results(authoritative_height, local_hash)

        mempool_txs = self._coerce_int(public_mempool, "size")
        mempool_bytes = self._coerce_int(public_mempool, "bytes")
        mempool_zero_started_at, mempool_zero_height = self._track_mempool_zero(
            previous_snapshot,
            mempool_txs,
            authoritative_height,
            generated_at_unix,
        )
        mempool_zero_duration = generated_at_unix - mempool_zero_started_at if mempool_zero_started_at else 0
        zero_window_has_new_blocks = bool(
            mempool_txs == 0
            and mempool_zero_started_at
            and authoritative_height is not None
            and mempool_zero_height is not None
            and authoritative_height > mempool_zero_height
        )

        recent_hashrate = previous_snapshot.get("recent_hashrate", [])
        if authoritative_height is not None and hashrate_hps is not None and hashrate_due:
            next_hashrate_point = build_hashrate_point(generated_at, authoritative_height, hashrate_hps)
            if not recent_hashrate or recent_hashrate[-1] != next_hashrate_point:
                recent_hashrate = self.cache.append_json_list(
                    "monitor:hashrate:recent",
                    next_hashrate_point,
                    self.settings.recent_block_window,
                )

        recent_block_intervals = build_interval_points(recent_blocks)
        self._replace_json_list_if_changed("monitor:intervals:recent", recent_block_intervals, previous_snapshot.get("recent_block_intervals", []))
        self._replace_json_list_if_changed("monitor:blocks:recent", recent_blocks, previous_snapshot.get("recent_blocks", []))
        self._set_cache_json_if_changed("monitor:last_height", authoritative_height, previous_snapshot.get("height"))

        cycle_duration = time.perf_counter() - cycle_started
        if self._rpc_cycle_used and cycle_duration > self.settings.poll_interval_seconds * 0.7:
            self._enter_rpc_cooldown("refresh_duration")

        rpc_local_status = self._rpc_status()
        cooldown_remaining_seconds = max(0, int(self._rpc_cooldown_until - time.monotonic()))
        cooldown_active_seconds = self._cooldown_active_seconds()
        self._sync_rpc_source_health(cooldown_remaining_seconds)

        alerts: list[dict[str, Any]] = []
        alerts.extend(fork_alerts)
        alerts.extend(detect_no_new_block_alert(recent_blocks, current_timestamp=generated_at_unix, block_target_seconds=self.settings.block_target_seconds))
        alerts.extend(
            detect_mempool_alert(
                mempool_txs=mempool_txs,
                mempool_zero_duration=mempool_zero_duration,
                zero_window_has_new_blocks=zero_window_has_new_blocks,
            )
        )
        alerts.extend(detect_rpc_health_alert(rpc_local_status=rpc_local_status, cooldown_active_seconds=cooldown_active_seconds))
        alerts.extend(detect_source_degraded_alert(self._source_health))
        alerts.extend(detect_site_health_alerts(public_sites))
        alerts.extend(self._build_split_alerts(comparison_results, authoritative_height, local_hash))

        # RPC Local Unavailable critical alert
        rpc_health = self._source_health.get("rpc_local", {})
        if rpc_health.get("status") in {"down", "degraded", "cooldown"}:
            alerts.append(
                build_alert(
                    "rpc_unavailable",
                    "critical",
                    "RPC unavailable",
                    f"Local RPC daemon is currently unavailable: {rpc_health.get('last_error') or rpc_health.get('status')}.",
                    source="rpc_local",
                    details={"status": rpc_health.get("status")},
                )
            )

        # Avg block time warning
        if avg_block_time_8m is not None and avg_block_time_8m > 40.0:
            alerts.append(
                build_alert(
                    "slow_average_block_time",
                    "warning",
                    "Average block time slow",
                    f"Average block time (8m) is {avg_block_time_8m:.2f} seconds, which is slower than 20 seconds.",
                    source="rpc_local",
                    details={"avg_block_time_8m": avg_block_time_8m},
                )
            )

        # Legacy masternodes remaining warning
        if masternode_summary.get("legacy_enabled", 0) > 0:
            alerts.append(
                build_alert(
                    "legacy_masternodes_remaining",
                    "warning",
                    "Legacy enabled masternodes remaining",
                    f"There are {masternode_summary['legacy_enabled']} legacy enabled masternodes running on the network. They may not follow the post-fork network correctly.",
                    source="monitor",
                    details={"legacy_enabled": masternode_summary["legacy_enabled"]},
                )
            )

        # One or more public services down warning
        down_services = [s.get("name") for s in public_sites if s.get("status") == "down"]
        if down_services:
            alerts.append(
                build_alert(
                    "public_services_down",
                    "warning",
                    "One or more public services unavailable",
                    f"The following public services are down: {', '.join(down_services)}.",
                    source="monitor",
                    details={"down_services": down_services},
                )
            )

        # Mining pool stratum connection warning
        failed_pools = [p.get("endpoint") for p in mining_pools if p.get("status") == "down"]
        if failed_pools:
            alerts.append(
                build_alert(
                    "mining_pool_probe_failed",
                    "warning",
                    "Mining pool probe failed",
                    f"Stratum connection failed for one or more mining pools: {', '.join(failed_pools)}.",
                    source="monitor",
                    details={"failed_pools": failed_pools},
                )
            )

        # Sharp drop in hashrate warning
        if len(recent_hashrate) >= 5:
            historical_values = [h["value"] for h in recent_hashrate[:-1]]
            avg_hist_hashrate = sum(historical_values) / len(historical_values)
            latest_hashrate = recent_hashrate[-1]["value"]
            if avg_hist_hashrate > 0 and latest_hashrate < avg_hist_hashrate * 0.5:
                percent_drop = round((1.0 - latest_hashrate / avg_hist_hashrate) * 100, 2)
                alerts.append(
                    build_alert(
                        "hashrate_drop",
                        "warning",
                        "Hashrate dropped sharply",
                        f"Hashrate dropped by {percent_drop}% compared to recent historical average.",
                        source="rpc_local",
                        details={"latest_hashrate": latest_hashrate, "historical_average": avg_hist_hashrate},
                    )
                )

        alerts = self._reconcile_alerts(sort_alerts(alerts), generated_at)
        services = previous_snapshot.get("services", {})
        if (
            previous_snapshot.get("source_health", {}) != self._source_health
            or previous_snapshot.get("services", {}).get("public_sites", []) != public_sites
            or previous_snapshot.get("services", {}).get("mining_pools", []) != mining_pools
            or previous_snapshot.get("services", {}).get("mining_pool_summary", {}) != mining_pool_summary
        ):
            services = self._build_services_summary(self._source_health, public_sites, mining_pools, mining_pool_summary)
        upgrade_summary = previous_snapshot.get("upgrade_summary", {})
        if not self._masternode_summary_matches_previous(previous_snapshot, masternode_summary):
            upgrade_summary = self._build_upgrade_summary(masternode_summary)
        recent_anomalies = self._build_recent_anomalies(alerts)
        freshness = self._build_freshness_snapshot(
            generated_at_unix=generated_at_unix,
            last_block_age=last_block_age,
            source_health=self._source_health,
            masternode_cache_generated_at_unix=masternode_cache_generated_at_unix,
            site_checks_generated_at_unix=site_checks_generated_at_unix,
        )

        snapshot = {
            "generated_at": generated_at,
            "generated_at_unix": generated_at_unix,
            "stale": False,
            "height": authoritative_height,
            "height_source": height_source,
            "rpc_height": rpc_height,
            "explorer_height": explorer_height,
            "public_height": public_height,
            "local_hash": local_hash,
            "hashrate_hps": round(float(hashrate_hps), 4) if hashrate_hps is not None else None,
            "hashrate_display": format_hashrate(hashrate_hps),
            "difficulty": round(float(difficulty), 12) if difficulty is not None else None,
            "peer_count": peer_count,
            "mempool_txs": mempool_txs,
            "mempool_size": mempool_txs,
            "mempool_bytes": mempool_bytes,
            "mempool_zero_duration": mempool_zero_duration,
            "avg_block_time_3m": round(avg_block_time_8m, 2) if avg_block_time_8m is not None else None,
            "avg_block_time_5m": round(avg_block_time_8m, 2) if avg_block_time_8m is not None else None,
            "avg_block_time_8m": round(avg_block_time_8m, 2) if avg_block_time_8m is not None else None,
            "avg_block_time_30m": round(avg_block_time_30m, 2) if avg_block_time_30m is not None else None,
            "avg_block_time_2h": round(avg_block_time_2h, 2) if avg_block_time_2h is not None else None,
            "avg_block_time_30blocks": round(avg_block_time_30m, 2) if avg_block_time_30m is not None else None,
            "last_block_age": last_block_age,
            "masternode_enabled": masternode_summary["enabled"],
            "masternode_total": masternode_summary["total"],
            "masternode_upgraded_enabled": masternode_summary["upgraded_enabled"],
            "masternode_legacy_enabled": masternode_summary["legacy_enabled"],
            "masternode_unknown_enabled": masternode_summary["unknown_enabled"],
            "masternode_versions": masternode_summary["versions"],
            "upgrade_ratio": masternode_summary["upgrade_ratio"],
            "target_version": self.settings.target_version,
            "rpc_local_status": rpc_local_status,
            "rpc_fail_streak": self._rpc_fail_count,
            "last_rpc_success_time": self._last_success_timestamp,
            "cooldown_remaining_seconds": cooldown_remaining_seconds,
            "fork": fork_status,
            "alerts": alerts,
            "recent_blocks": recent_blocks,
            "recent_hashrate": recent_hashrate,
            "recent_block_intervals": recent_block_intervals,
            "comparison_results": comparison_results,
            "source_health": self._source_health,
            "peers": {
                "summary": peer_summary,
                "items": peer_items,
            },
            "services": services,
            "upgrade_summary": upgrade_summary,
            "recent_anomalies": recent_anomalies,
            "freshness": freshness,
            "_peerinfo_raw": peers_raw,
            "_public_mempool": public_mempool,
            "_mempool_zero_started_at": mempool_zero_started_at,
            "_mempool_zero_height": mempool_zero_height,
            "_site_checks_generated_at": site_checks_generated_at,
            "_site_checks_generated_at_unix": site_checks_generated_at_unix,
            "_masternode_cache_generated_at": masternode_cache_generated_at,
            "_masternode_cache_generated_at_unix": masternode_cache_generated_at_unix,
            "_masternode_summary_fingerprint": masternode_summary_fingerprint,
            "_services_generated_at_unix": generated_at_unix if services != previous_snapshot.get("services", {}) else previous_snapshot.get("_services_generated_at_unix"),
            "_recent_anomalies_generated_at_unix": generated_at_unix,
        }

        self.cache.set_json("monitor:latest", snapshot)
        self._set_cache_json_if_changed("monitor:source_health", self._source_health, previous_snapshot.get("source_health", {}))
        self._latest_snapshot = snapshot
        self.logger.info(
            "monitor refresh complete height=%s alerts=%s cache=%s rpc=%s",
            authoritative_height,
            len(alerts),
            self.cache.name,
            rpc_local_status,
        )

    async def _fetch_rpc_height(self, previous_snapshot: dict[str, Any]) -> int | None:
        if not self._rpc_can_call("getblockcount"):
            return previous_snapshot.get("rpc_height")
        rpc_height = await self._source_call("rpc_local", "rpc", self.sources.rpc_get_blockcount, rpc_operation="getblockcount")
        return previous_snapshot.get("rpc_height") if rpc_height is None and self._probe_only_mode else rpc_height

    async def _collect_masternode_summary(
        self,
        peers_raw: list[dict[str, Any]],
        previous_summary: dict[str, Any],
        *,
        previous_fingerprint: str | None,
        previous_generated_at: str | None,
        previous_generated_at_unix: int | None,
        generated_at: str,
        generated_at_unix: int,
    ) -> tuple[dict[str, Any], str | None, str | None, int | None]:
        masternode_count: dict[str, int] | None = None
        masternode_list: list[dict[str, Any]] = []
        rpc_masternode_list: list[dict[str, Any]] = []

        masternode_count = await self._source_call("explorer_local", "explorer", self.sources.explorer_get_masternodecount)
        masternode_list = await self._source_call("explorer_local", "explorer", self.sources.explorer_get_masternodelist) or []

        expected_total = int((masternode_count or {}).get("total", 0) or 0)
        explorer_incomplete = expected_total > 0 and len(masternode_list) < expected_total

        if (masternode_count is None or not masternode_list or explorer_incomplete) and not self._probe_only_mode:
            if masternode_count is None:
                masternode_count = await self._source_call("rpc_local", "rpc", self.sources.rpc_get_masternodecount, rpc_operation="getmasternodecount")
            rpc_masternode_list = await self._source_call("rpc_local", "rpc", self.sources.rpc_get_masternodelist, rpc_operation="getmasternodelist") or []
            if not masternode_list:
                masternode_list = rpc_masternode_list

        merged_masternodes = merge_masternode_records(masternode_list, rpc_masternode_list)

        if masternode_count is None and not merged_masternodes:
            return previous_summary, previous_fingerprint, previous_generated_at, previous_generated_at_unix

        normalized_items = normalize_masternode_items(merged_masternodes)
        adjusted_count = dict(masternode_count or {})
        adjusted_count["total"] = max(int(adjusted_count.get("total", 0) or 0), len(merged_masternodes))
        adjusted_count["enabled"] = max(
            int(adjusted_count.get("enabled", 0) or 0),
            len([item for item in merged_masternodes if is_enabled_masternode(item)]),
        )
        fingerprint = build_masternode_summary_fingerprint(merged_masternodes, adjusted_count, peers_raw)

        cached_masternodes = self.cache.get_json(self._MASTERNODES_CACHE_KEY, {}) or {}
        cached_items = cached_masternodes.get("items", [])
        if normalized_items and normalized_items != cached_items:
            self.cache.set_json(
                self._MASTERNODES_CACHE_KEY,
                {
                    "generated_at": generated_at,
                    "generated_at_unix": generated_at_unix,
                    "items": normalized_items,
                },
            )

        if fingerprint == previous_fingerprint:
            return previous_summary, fingerprint, generated_at, generated_at_unix

        return (
            build_masternode_summary(merged_masternodes, adjusted_count, self.settings.min_upgraded_subver, peers_raw),
            fingerprint,
            generated_at,
            generated_at_unix,
        )

    async def _collect_site_status(
        self,
        previous_sites: list[dict[str, Any]],
        generated_at: str,
        generated_at_unix: int,
    ) -> tuple[list[dict[str, Any]], str | None, int | None]:
        previous_by_name = {
            str(site.get("name")): site
            for site in previous_sites
            if isinstance(site, dict) and site.get("name")
        }

        async def probe(target) -> dict[str, Any]:
            previous = previous_by_name.get(target.name, {})
            try:
                payload = await self.sources.check_site(target.url)
                status_code = payload.get("status_code")
                status = "ok"
                if status_code is None:
                    status = "degraded"
                elif int(status_code) >= 500:
                    status = "down"
                elif int(status_code) >= 400:
                    status = "degraded"
                return {
                    "name": target.name,
                    "url": target.url,
                    "status": status,
                    "status_code": status_code,
                    "latency_ms": payload.get("latency_ms"),
                    "last_checked_at": generated_at,
                    "last_success_at": generated_at if status == "ok" else previous.get("last_success_at"),
                    "last_error": None if status == "ok" else f"http {status_code}",
                    "consecutive_failures": 0 if status == "ok" else int(previous.get("consecutive_failures", 0) or 0) + 1,
                }
            except Exception as exc:
                failures = int(previous.get("consecutive_failures", 0) or 0) + 1
                return {
                    "name": target.name,
                    "url": target.url,
                    "status": "down" if failures >= self.settings.source_failure_threshold else "degraded",
                    "status_code": previous.get("status_code"),
                    "latency_ms": previous.get("latency_ms"),
                    "last_checked_at": generated_at,
                    "last_success_at": previous.get("last_success_at"),
                    "last_error": str(exc) or exc.__class__.__name__,
                    "consecutive_failures": failures,
                }

        tasks = [probe(target) for target in self.settings.site_status_targets if target.enabled]
        if not tasks:
            return previous_sites, None, None

        results = await asyncio.gather(*tasks)
        results.sort(key=lambda item: item["name"])
        return results, generated_at, generated_at_unix

    def _build_services_summary(
        self,
        source_health: dict[str, dict[str, Any]],
        public_sites: list[dict[str, Any]],
        mining_pools: list[dict[str, Any]],
        mining_pool_summary: dict[str, Any],
    ) -> dict[str, Any]:
        core_sources = {
            key: value
            for key, value in source_health.items()
            if key in {"rpc_local", "explorer_local", "public_api_remote"}
        }
        statuses = [str(item.get("status") or "unknown") for item in core_sources.values()]
        statuses.extend(str(item.get("status") or "unknown") for item in public_sites)
        ok_count = sum(1 for status in statuses if status == "ok")
        degraded_count = sum(1 for status in statuses if status == "degraded")
        down_count = sum(1 for status in statuses if status in {"down", "cooldown"})

        overall_status = "ok"
        if down_count > 0:
            overall_status = "down"
        elif degraded_count > 0:
            overall_status = "degraded"

        return {
            "summary": {
                "overall_status": overall_status,
                "ok_count": ok_count,
                "degraded_count": degraded_count,
                "down_count": down_count,
                "core_sources_ok": sum(1 for item in core_sources.values() if item.get("status") == "ok"),
                "public_sites_ok": sum(1 for item in public_sites if item.get("status") == "ok"),
            },
            "core_sources": core_sources,
            "public_sites": public_sites,
            "mining_pool_summary": mining_pool_summary,
            "mining_pools": mining_pools,
        }

    async def _collect_mining_pool_status(
        self,
        previous_pools: list[dict[str, Any]],
        generated_at: str,
        generated_at_unix: int,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        previous_by_endpoint = {
            str(pool.get("endpoint")): pool
            for pool in previous_pools
            if isinstance(pool, dict) and pool.get("endpoint")
        }
        semaphore = asyncio.Semaphore(2)

        async def probe(target) -> dict[str, Any]:
            endpoint = target.name if target.name else f"{target.host}:{target.port}"
            previous = previous_by_endpoint.get(endpoint, {})
            try:
                async with semaphore:
                    payload = await self.sources.check_mining_pool(target.host, target.port)
            except Exception as exc:
                payload = {
                    "tcp_connect_ok": False,
                    "stratum_ok": False,
                    "latency_ms": None,
                    "error": str(exc) or exc.__class__.__name__,
                }

            tcp_connect_ok = bool(payload.get("tcp_connect_ok"))
            stratum_ok = bool(payload.get("stratum_ok"))
            if stratum_ok:
                status = "up"
            elif tcp_connect_ok:
                status = "degraded"
            else:
                status = "down"

            return {
                "endpoint": endpoint,
                "host": target.host,
                "port": int(target.port),
                "tcp_connect_ok": tcp_connect_ok,
                "stratum_ok": stratum_ok,
                "latency_ms": payload.get("latency_ms"),
                "checked_at": generated_at,
                "last_ok_at": generated_at if stratum_ok else previous.get("last_ok_at"),
                "status": status,
                "error": None if stratum_ok else payload.get("error"),
            }

        tasks = [probe(target) for target in self.settings.mining_pool_targets if target.enabled]
        if not tasks:
            return previous_pools, self._build_mining_pool_summary(previous_pools)

        results = await asyncio.gather(*tasks)
        results.sort(key=lambda item: item["endpoint"])
        return results, self._build_mining_pool_summary(results)

    def _build_mining_pool_summary(self, pools: list[dict[str, Any]]) -> dict[str, int]:
        return {
            "total_pools": len(pools),
            "reachable_pools": sum(1 for item in pools if item.get("tcp_connect_ok")),
            "healthy_stratum_pools": sum(1 for item in pools if item.get("stratum_ok")),
            "up_count": sum(1 for item in pools if item.get("status") == "up"),
            "degraded_count": sum(1 for item in pools if item.get("status") == "degraded"),
            "down_count": sum(1 for item in pools if item.get("status") == "down"),
        }

    def _build_upgrade_summary(self, masternode_summary: dict[str, Any]) -> dict[str, Any]:
        unknown_enabled = int(masternode_summary.get("unknown_enabled", 0) or 0)
        enabled = int(masternode_summary.get("enabled", 0) or 0)
        classification_status = "complete" if enabled and unknown_enabled == 0 else "partial_unknown"
        if enabled == 0:
            classification_status = "unknown"
        return {
            "enabled": enabled,
            "upgraded": int(masternode_summary.get("upgraded_enabled", 0) or 0),
            "legacy": int(masternode_summary.get("legacy_enabled", 0) or 0),
            "unknown": unknown_enabled,
            "ratio": float(masternode_summary.get("upgrade_ratio", 0.0) or 0.0),
            "classification_status": classification_status,
        }

    def _build_recent_anomalies(self, alerts: list[dict[str, Any]], window_hours: int = 24) -> dict[str, Any]:
        history = self.cache.get_json("monitor:alerts:recent", []) or []
        cutoff = int(time.time()) - (window_hours * 3600)
        recent_events = []
        for item in history:
            timestamp = item.get("timestamp")
            event_ts = None
            if timestamp:
                try:
                    event_ts = int(datetime.fromisoformat(timestamp).timestamp())
                except ValueError:
                    event_ts = None
            if event_ts is not None and event_ts >= cutoff:
                recent_events.append(item)

        latest = recent_events[-5:]
        return {
            "window_hours": window_hours,
            "raised_count": sum(1 for item in recent_events if item.get("event") == "raised"),
            "cleared_count": sum(1 for item in recent_events if item.get("event") == "cleared"),
            "active_critical_count": sum(1 for item in alerts if item.get("severity") == "critical"),
            "latest": latest,
        }

    def _build_freshness_snapshot(
        self,
        *,
        generated_at_unix: int,
        last_block_age: int | None,
        source_health: dict[str, dict[str, Any]],
        masternode_cache_generated_at_unix: int | None,
        site_checks_generated_at_unix: int | None,
    ) -> dict[str, Any]:
        thresholds = self._freshness_thresholds()
        daemon_age = self._daemon_data_age(generated_at_unix, last_block_age, source_health)
        explorer_age = self._age_from_timestamp(source_health.get("explorer_local", {}).get("last_success_at"), generated_at_unix)
        snapshot = {
            "snapshot_age_seconds": 0,
            "mn_cache_age_seconds": self._age_from_unix(masternode_cache_generated_at_unix, generated_at_unix),
            "masternode_list_age_seconds": self._age_from_unix(masternode_cache_generated_at_unix, generated_at_unix),
            "site_status_age_seconds": self._age_from_unix(site_checks_generated_at_unix, generated_at_unix),
            "site_checks_age_seconds": self._age_from_unix(site_checks_generated_at_unix, generated_at_unix),
            "daemon_data_age_seconds": daemon_age,
            "explorer_data_age_seconds": explorer_age,
            "last_block_age_seconds": last_block_age,
            "status": "normal",
            "thresholds": thresholds,
        }
        snapshot.update(self._freshness_status_fields(snapshot, thresholds))
        return snapshot

    def _apply_live_snapshot_age(self, snapshot: dict[str, Any], now_unix: int) -> dict[str, Any]:
        adjusted = dict(snapshot)
        adjusted["masternode_versions"] = self._coerce_masternode_versions(adjusted.get("masternode_versions", []))
        generated_at_unix = adjusted.get("generated_at_unix")
        delta = self._age_from_unix(generated_at_unix, now_unix) or 0
        adjusted["stale"] = delta > self.settings.stale_after_seconds if generated_at_unix is not None else True

        freshness = dict(adjusted.get("freshness", {}))
        thresholds = freshness.get("thresholds") or self._freshness_thresholds()
        freshness["thresholds"] = thresholds
        freshness["snapshot_age_seconds"] = delta if generated_at_unix is not None else None
        for key in (
            "mn_cache_age_seconds",
            "masternode_list_age_seconds",
            "site_status_age_seconds",
            "site_checks_age_seconds",
            "daemon_data_age_seconds",
            "explorer_data_age_seconds",
            "last_block_age_seconds",
        ):
            base_value = freshness.get(key)
            if base_value is not None:
                freshness[key] = int(base_value) + delta

        if adjusted.get("last_block_age") is not None:
            adjusted["last_block_age"] = int(adjusted["last_block_age"]) + delta
        freshness["last_block_age_seconds"] = adjusted.get("last_block_age")
        freshness.update(self._freshness_status_fields(freshness, thresholds))
        if generated_at_unix is None:
            freshness["snapshot_status"] = "critical_stale"
            freshness["overall_status"] = self._max_freshness_level(freshness.get("overall_status", "normal"), "critical_stale")
            freshness["status"] = freshness["overall_status"]
        adjusted["freshness"] = freshness

        if adjusted.get("stale"):
            existing_alerts = list(adjusted.get("alerts", []))
            if not any(a.get("type") == "snapshot_stale" for a in existing_alerts):
                existing_alerts.append({
                    "id": "snapshot_stale:monitor",
                    "type": "snapshot_stale",
                    "severity": "critical",
                    "title": "Last snapshot stale",
                    "message": "The monitor snapshot data is stale. Check scheduler health.",
                    "source": "monitor",
                    "details": {}
                })
                adjusted["alerts"] = existing_alerts
        return adjusted

    def _freshness_thresholds(self) -> dict[str, dict[str, int]]:
        return {
            "snapshot": {
                "stale": max(self.settings.poll_interval_seconds * 2, 10),
                "critical": max(self.settings.poll_interval_seconds * 6, 30),
            },
            "mn_cache": {
                "stale": self.settings.masternode_interval_seconds * 2,
                "critical": self.settings.masternode_interval_seconds * 4,
            },
            "site_status": {
                "stale": self.settings.site_status_interval_seconds * 2,
                "critical": self.settings.site_status_interval_seconds * 4,
            },
            "daemon": {
                "stale": self.settings.rpc_blockcount_poll_interval_seconds * 2,
                "critical": self.settings.rpc_blockcount_poll_interval_seconds * 6,
            },
            "explorer": {
                "stale": self.settings.rpc_blockcount_poll_interval_seconds * 2,
                "critical": self.settings.rpc_blockcount_poll_interval_seconds * 6,
            },
            "last_block": {
                "stale": self.settings.block_target_seconds * 2,
                "critical": self.settings.block_target_seconds * 4,
            },
        }

    def _freshness_status_fields(
        self,
        freshness: dict[str, Any],
        thresholds: dict[str, dict[str, int]],
    ) -> dict[str, Any]:
        snapshot_status = self._freshness_level(freshness.get("snapshot_age_seconds"), thresholds.get("snapshot", {}))
        mn_cache_status = self._freshness_level(freshness.get("mn_cache_age_seconds"), thresholds.get("mn_cache", {}))
        site_status_status = self._freshness_level(freshness.get("site_status_age_seconds"), thresholds.get("site_status", {}))
        daemon_status = self._freshness_level(freshness.get("daemon_data_age_seconds"), thresholds.get("daemon", {}))
        explorer_status = self._freshness_level(freshness.get("explorer_data_age_seconds"), thresholds.get("explorer", {}))
        last_block_status = self._freshness_level(freshness.get("last_block_age_seconds"), thresholds.get("last_block", {}))
        overall_status = self._max_freshness_level(
            snapshot_status,
            mn_cache_status,
            site_status_status,
            daemon_status,
            explorer_status,
            last_block_status,
        )
        return {
            "snapshot_status": snapshot_status,
            "mn_cache_status": mn_cache_status,
            "site_status_status": site_status_status,
            "daemon_status": daemon_status,
            "explorer_status": explorer_status,
            "last_block_status": last_block_status,
            "overall_status": overall_status,
            "status": overall_status,
        }

    def _freshness_level(self, age_seconds: int | None, thresholds: dict[str, int]) -> str:
        if age_seconds is None:
            return "normal"
        if age_seconds > int(thresholds.get("critical", 0) or 0):
            return "critical_stale"
        if age_seconds > int(thresholds.get("stale", 0) or 0):
            return "stale"
        return "normal"

    def _max_freshness_level(self, *levels: str) -> str:
        order = {"normal": 0, "stale": 1, "critical_stale": 2}
        selected = "normal"
        for level in levels:
            if order.get(level, -1) > order.get(selected, -1):
                selected = level
        return selected

    def _daemon_data_age(
        self,
        generated_at_unix: int,
        last_block_age: int | None,
        source_health: dict[str, dict[str, Any]],
    ) -> int | None:
        daemon_age = self._age_from_timestamp(source_health.get("rpc_local", {}).get("last_success_at"), generated_at_unix)
        if daemon_age is not None:
            return daemon_age
        return last_block_age

    def _age_from_timestamp(self, timestamp: str | None, now_unix: int) -> int | None:
        if not timestamp:
            return None
        try:
            return max(0, now_unix - int(datetime.fromisoformat(timestamp).timestamp()))
        except ValueError:
            return None

    def _masternode_summary_matches_previous(
        self,
        previous_snapshot: dict[str, Any],
        summary: dict[str, Any],
    ) -> bool:
        return (
            int(previous_snapshot.get("masternode_enabled", 0) or 0) == int(summary.get("enabled", 0) or 0)
            and int(previous_snapshot.get("masternode_total", 0) or 0) == int(summary.get("total", 0) or 0)
            and int(previous_snapshot.get("masternode_upgraded_enabled", 0) or 0) == int(summary.get("upgraded_enabled", 0) or 0)
            and int(previous_snapshot.get("masternode_legacy_enabled", 0) or 0) == int(summary.get("legacy_enabled", 0) or 0)
            and int(previous_snapshot.get("masternode_unknown_enabled", 0) or 0) == int(summary.get("unknown_enabled", 0) or 0)
            and float(previous_snapshot.get("upgrade_ratio", 0.0) or 0.0) == float(summary.get("upgrade_ratio", 0.0) or 0.0)
            and self._coerce_masternode_versions(previous_snapshot.get("masternode_versions", [])) == summary.get("versions", [])
        )

    def _replace_json_list_if_changed(self, key: str, values: list[Any], previous: list[Any]) -> None:
        if values != previous:
            self.cache.replace_json_list(key, values)

    def _set_cache_json_if_changed(self, key: str, value: Any, previous: Any) -> None:
        if value != previous:
            self.cache.set_json(key, value)

    def _age_from_unix(self, value: Any, now_unix: int) -> int | None:
        if value is None:
            return None
        try:
            return max(0, now_unix - int(value))
        except (TypeError, ValueError):
            return None

    async def _source_call(
        self,
        name: str,
        kind: str,
        callback: Callable[[], Awaitable[Any]],
        *,
        rpc_operation: str | None = None,
    ) -> Any:
        if kind == "rpc" and not self._rpc_can_call(rpc_operation):
            return None

        last_error: Exception | None = None
        for attempt in range(self.settings.request_retries + 1):
            started = time.perf_counter()
            try:
                result = await callback()
                latency_seconds = time.perf_counter() - started
                latency_ms = round(latency_seconds * 1000, 2)
                self._mark_source_success(name, kind, latency_ms)
                if kind == "rpc":
                    self._rpc_cycle_used = True
                    self._last_success_timestamp = datetime.now(timezone.utc).isoformat()
                    if latency_seconds > 2.0:
                        self._enter_rpc_cooldown(f"{rpc_operation or 'rpc'}_slow")
                    elif self._probe_only_mode and rpc_operation == "getblockcount":
                        self._probe_success_streak += 1
                        if self._probe_success_streak >= 2:
                            self._probe_only_mode = False
                            self._probe_success_streak = 0
                            self._rpc_cooldown_started_at = 0.0
                return result
            except Exception as exc:
                last_error = exc
                if attempt < self.settings.request_retries:
                    delay = self.settings.request_retry_backoff_seconds[min(attempt, len(self.settings.request_retry_backoff_seconds) - 1)]
                    await asyncio.sleep(delay)

        message = str(last_error) if last_error else "unknown error"
        if not message and last_error is not None:
            message = last_error.__class__.__name__
        self._mark_source_failure(name, kind, message)
        if kind == "rpc" and (self._probe_only_mode or self._rpc_fail_count >= self.settings.rpc_fail_threshold):
            self._enter_rpc_cooldown(f"{rpc_operation or 'rpc'}_failed")
        return None

    def _mark_source_success(self, name: str, kind: str, latency_ms: float) -> None:
        previous = self._source_health.get(name, {})
        if kind == "rpc":
            self._rpc_fail_count = 0
        self._source_health[name] = {
            "name": name,
            "kind": kind,
            "status": "ok",
            "latency_ms": latency_ms,
            "last_success_at": datetime.now(timezone.utc).isoformat(),
            "last_error": None,
            "consecutive_failures": 0,
            "cooldown_remaining_seconds": previous.get("cooldown_remaining_seconds", 0),
        }

    def _mark_source_failure(self, name: str, kind: str, error: str) -> None:
        previous = self._source_health.get(name, {})
        failures = int(previous.get("consecutive_failures", 0)) + 1
        status = "degraded"
        if failures >= self.settings.source_failure_threshold and not previous.get("last_success_at"):
            status = "down"
        self._source_health[name] = {
            "name": name,
            "kind": kind,
            "status": status,
            "latency_ms": previous.get("latency_ms"),
            "last_success_at": previous.get("last_success_at"),
            "last_error": error,
            "consecutive_failures": failures,
            "cooldown_remaining_seconds": previous.get("cooldown_remaining_seconds", 0),
        }
        if kind == "rpc":
            self._rpc_fail_count += 1

    async def _refresh_recent_blocks(
        self,
        authoritative_height: int,
        cached: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        buffer = deque(list(cached)[-self.settings.recent_block_window :], maxlen=self.settings.recent_block_window)
        working = list(buffer)
        if not working or authoritative_height < working[-1]["height"] or authoritative_height - working[-1]["height"] > self.settings.recent_block_window:
            return await self._cold_start_recent_blocks(authoritative_height)

        while working:
            tail_height = int(working[-1]["height"])
            remote_tail_hash = await self._source_call(
                "rpc_local",
                "rpc",
                lambda current_height=tail_height: self.sources.rpc_get_blockhash(current_height),
                rpc_operation="getblockhash",
            )
            if remote_tail_hash is None:
                return self._recalculate_block_intervals(working)
            if remote_tail_hash == working[-1]["hash"]:
                break
            working.pop()

        if not working:
            return await self._cold_start_recent_blocks(authoritative_height)

        fetch_start = int(working[-1]["height"]) + 1
        if fetch_start > authoritative_height:
            return self._recalculate_block_intervals(working)

        fetch_end = min(authoritative_height, fetch_start + self.settings.block_fetch_limit_per_cycle - 1)
        previous_time = working[-1].get("time")
        for height in range(fetch_start, fetch_end + 1):
            sample = await self._fetch_block_sample(height, previous_time)
            if sample is None:
                break
            previous_time = sample.get("time")
            working.append(sample)

        return self._recalculate_block_intervals(working)

    async def _cold_start_recent_blocks(self, authoritative_height: int) -> list[dict[str, Any]]:
        fetch_limit = min(self.settings.block_fetch_limit_per_cycle, self.settings.block_history_cold_start_limit)
        fetch_start = max(authoritative_height - fetch_limit + 1, 0)
        blocks: list[dict[str, Any]] = []
        previous_time: int | None = None
        for height in range(fetch_start, authoritative_height + 1):
            sample = await self._fetch_block_sample(height, previous_time)
            if sample is None:
                continue
            previous_time = sample.get("time")
            blocks.append(sample)
        return self._recalculate_block_intervals(blocks)

    async def _fetch_block_sample(self, height: int, previous_time: int | None) -> dict[str, Any] | None:
        blockhash = await self._source_call(
            "rpc_local",
            "rpc",
            lambda current_height=height: self.sources.rpc_get_blockhash(current_height),
            rpc_operation="getblockhash",
        )
        if blockhash is None:
            return None
        block = await self._source_call(
            "rpc_local",
            "rpc",
            lambda current_hash=blockhash: self.sources.rpc_get_block(current_hash),
            rpc_operation="getblock",
        )
        if block is None:
            return None
        return block_to_sample(
            block,
            previous_time,
            "rpc_local",
            self.settings.hoohash_bit,
            self.settings.xelis_bit,
        )

    def _recalculate_block_intervals(self, blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        previous_time: int | None = None
        normalized: list[dict[str, Any]] = []
        for block in sorted(blocks, key=lambda item: int(item["height"])):
            item = dict(block)
            block_time = item.get("time")
            item["interval_from_prev"] = (block_time - previous_time) if previous_time is not None and block_time is not None else None
            previous_time = block_time if block_time is not None else previous_time
            normalized.append(item)
        return normalized[-self.settings.recent_block_window :]

    def _rpc_can_call(self, rpc_operation: str | None) -> bool:
        now = time.monotonic()
        if now < self._rpc_cooldown_until:
            return False
        if self._probe_only_mode:
            return rpc_operation == "getblockcount"
        return True

    def _enter_rpc_cooldown(self, reason: str) -> None:
        now = time.monotonic()
        if self._rpc_cooldown_started_at == 0.0:
            self._rpc_cooldown_started_at = now
        self._rpc_cooldown_until = now + self.settings.rpc_failure_cooldown_seconds
        self._probe_only_mode = True
        self._probe_success_streak = 0
        previous = self._source_health.get("rpc_local", {})
        self._source_health["rpc_local"] = {
            "name": "rpc_local",
            "kind": "rpc",
            "status": "cooldown",
            "latency_ms": previous.get("latency_ms"),
            "last_success_at": previous.get("last_success_at", self._last_success_timestamp),
            "last_error": reason,
            "consecutive_failures": self._rpc_fail_count,
            "cooldown_remaining_seconds": self.settings.rpc_failure_cooldown_seconds,
        }

    def _should_poll(self, key: str, interval_seconds: int, now_monotonic: float) -> bool:
        last_run = self._last_probe_at.get(key)
        if last_run is not None and (now_monotonic - last_run) < interval_seconds:
            return False
        self._last_probe_at[key] = now_monotonic
        return True

    def _sync_rpc_source_health(self, cooldown_remaining_seconds: int) -> None:
        previous = self._source_health.get("rpc_local", {})
        status = self._rpc_status()
        if not previous:
            self._source_health["rpc_local"] = {
                "name": "rpc_local",
                "kind": "rpc",
                "status": status,
                "latency_ms": None,
                "last_success_at": self._last_success_timestamp,
                "last_error": None,
                "consecutive_failures": self._rpc_fail_count,
                "cooldown_remaining_seconds": cooldown_remaining_seconds,
            }
            return
        previous["status"] = status
        previous["consecutive_failures"] = self._rpc_fail_count
        previous["last_success_at"] = previous.get("last_success_at") or self._last_success_timestamp
        previous["cooldown_remaining_seconds"] = cooldown_remaining_seconds

    def _rpc_status(self) -> str:
        if self._probe_only_mode or time.monotonic() < self._rpc_cooldown_until:
            return "cooldown"
        if self._rpc_fail_count > 0:
            return "degraded"
        return self._source_health.get("rpc_local", {}).get("status", "ok")

    def _cooldown_active_seconds(self) -> int:
        if not self._probe_only_mode or self._rpc_cooldown_started_at == 0.0:
            return 0
        return max(0, int(time.monotonic() - self._rpc_cooldown_started_at))

    def _calculate_block_timing(self, recent_blocks: list[dict[str, Any]], now_unix: int) -> tuple[float | None, float | None, float | None, int | None]:
        recent_8m = [
            float(block["interval_from_prev"])
            for block in recent_blocks
            if block.get("interval_from_prev") is not None and block.get("time") is not None and (now_unix - int(block["time"])) <= 480
        ]
        recent_30m = [
            float(block["interval_from_prev"])
            for block in recent_blocks
            if block.get("interval_from_prev") is not None and block.get("time") is not None and (now_unix - int(block["time"])) <= 1800
        ]
        recent_2h = [
            float(block["interval_from_prev"])
            for block in recent_blocks
            if block.get("interval_from_prev") is not None and block.get("time") is not None and (now_unix - int(block["time"])) <= 7200
        ]
        latest_block = recent_blocks[-1] if recent_blocks else None
        last_block_age = (now_unix - int(latest_block["time"])) if latest_block and latest_block.get("time") is not None else None
        return average(recent_8m), average(recent_30m), average(recent_2h), last_block_age

    def _track_mempool_zero(
        self,
        previous_snapshot: dict[str, Any],
        mempool_txs: int | None,
        authoritative_height: int | None,
        now_unix: int,
    ) -> tuple[int | None, int | None]:
        previous_started = previous_snapshot.get("_mempool_zero_started_at")
        previous_height = previous_snapshot.get("_mempool_zero_height")
        if mempool_txs == 0:
            if previous_snapshot.get("mempool_txs") == 0 and previous_started:
                return int(previous_started), previous_height
            return now_unix, authoritative_height
        return None, None

    def _pick_height(
        self,
        rpc_height: int | None,
        explorer_height: int | None,
        public_height: int | None,
        previous_height: int | None,
    ) -> int | None:
        if rpc_height is not None:
            return rpc_height
        if explorer_height is not None:
            return explorer_height
        if public_height is not None:
            return public_height
        return previous_height

    def _pick_height_source(
        self,
        rpc_height: int | None,
        explorer_height: int | None,
        public_height: int | None,
        previous_height_source: str | None,
    ) -> str | None:
        if rpc_height is not None:
            return "rpc_local"
        if explorer_height is not None:
            return "explorer_local"
        if public_height is not None:
            return "public_api_remote"
        return previous_height_source

    async def _collect_comparison_results(self, authoritative_height: int | None, local_hash: str | None) -> list[dict[str, Any]]:
        if authoritative_height is None:
            return []

        results: list[dict[str, Any]] = []
        for source in self.settings.comparison_sources:
            if not source.enabled:
                continue

            source_name = f"comparison:{source.name}"
            payload = await self._source_call(
                source_name,
                "comparison",
                lambda current_source=source: self.sources.comparison_get_state(current_source, authoritative_height),
            )
            if payload is None:
                results.append(
                    {
                        "name": source.name,
                        "type": source.type,
                        "status": "unavailable",
                        "remote_height": None,
                        "remote_hash": None,
                        "local_height": authoritative_height,
                        "local_hash": local_hash,
                        "match_state": "unavailable",
                        "active_alert": self._split_state.get(source.name, {}).get("active", False),
                    }
                )
                continue

            remote_height = payload.get("height")
            remote_hash = payload.get("hash")
            if remote_height != authoritative_height:
                match_state = "height_mismatch"
            elif remote_hash and local_hash and remote_hash == local_hash:
                match_state = "matched"
            elif remote_hash and local_hash and remote_hash != local_hash:
                match_state = "mismatch"
            else:
                match_state = "unavailable"

            results.append(
                {
                    "name": source.name,
                    "type": source.type,
                    "status": "ok",
                    "remote_height": remote_height,
                    "remote_hash": remote_hash,
                    "local_height": authoritative_height,
                    "local_hash": local_hash,
                    "match_state": match_state,
                    "active_alert": self._split_state.get(source.name, {}).get("active", False),
                }
            )

        return results

    def _build_split_alerts(
        self,
        comparison_results: list[dict[str, Any]],
        local_height: int | None,
        local_hash: str | None,
    ) -> list[dict[str, Any]]:
        if not comparison_results:
            return []

        alerts: list[dict[str, Any]] = []
        for result in comparison_results:
            name = result["name"]
            state = self._split_state.setdefault(
                name,
                {"active": False, "matching_polls": 0, "last_remote_hash": None, "last_remote_height": None},
            )

            match_state = result["match_state"]
            if match_state == "mismatch":
                state["active"] = True
                state["matching_polls"] = 0
                state["last_remote_hash"] = result["remote_hash"]
                state["last_remote_height"] = result["remote_height"]
            elif match_state == "matched" and state["active"]:
                state["matching_polls"] += 1
                if state["matching_polls"] >= self.settings.split_match_clear_polls:
                    state["active"] = False
                    state["matching_polls"] = 0

            result["active_alert"] = state["active"]
            if state["active"]:
                alerts.append(
                    build_alert(
                        "chain_split",
                        "critical",
                        "Chain split detected",
                        f"{name} returned a different block hash at height {local_height}.",
                        source=name,
                        details={
                            "local_height": local_height,
                            "local_hash": local_hash,
                            "remote_height": result["remote_height"],
                            "remote_hash": result["remote_hash"],
                            "id_suffix": name,
                        },
                    )
                )

            # Check height divergence
            remote_height = result.get("remote_height")
            if remote_height is not None and local_height is not None:
                height_diff = abs(remote_height - local_height)
                if height_diff >= 5:
                    alerts.append(
                        build_alert(
                            "height_divergence",
                            "critical",
                            "Large height divergence between nodes",
                            f"Comparison node {name} is at height {remote_height}, which diverges from local height {local_height} by {height_diff} blocks.",
                            source=name,
                            details={
                                "local_height": local_height,
                                "remote_height": remote_height,
                                "divergence_blocks": height_diff,
                                "id_suffix": name,
                            },
                        )
                    )
        return alerts

    def _reconcile_alerts(self, alerts: list[dict[str, Any]], timestamp: str) -> list[dict[str, Any]]:
        next_active: dict[str, dict[str, Any]] = {}
        history = self.cache.get_json("monitor:alerts:recent", [])

        for alert in alerts:
            existing = self._active_alerts.get(alert["id"])
            alert["active_since"] = existing.get("active_since") if existing else timestamp
            if not existing:
                history.append({"event": "raised", "timestamp": timestamp, "alert": alert})
            next_active[alert["id"]] = alert

        for alert_id, alert in self._active_alerts.items():
            if alert_id not in next_active:
                history.append({"event": "cleared", "timestamp": timestamp, "alert": alert})

        history = history[-100:]
        self.cache.set_json("monitor:alerts:recent", history)
        self._active_alerts = next_active
        return list(next_active.values())

    def _coerce_int(self, payload: dict[str, Any] | None, key: str) -> int | None:
        if not payload:
            return None
        try:
            return int(payload.get(key))
        except (TypeError, ValueError):
            return None

    def _empty_snapshot(self) -> dict[str, Any]:
        return {
            "generated_at": None,
            "generated_at_unix": None,
            "stale": True,
            "height": None,
            "height_source": None,
            "rpc_height": None,
            "explorer_height": None,
            "public_height": None,
            "local_hash": None,
            "hashrate_hps": None,
            "hashrate_display": "-",
            "difficulty": None,
            "peer_count": 0,
            "mempool_txs": None,
            "mempool_size": None,
            "mempool_bytes": None,
            "mempool_zero_duration": 0,
            "avg_block_time_3m": None,
            "avg_block_time_5m": None,
            "avg_block_time_8m": None,
            "avg_block_time_30m": None,
            "avg_block_time_2h": None,
            "avg_block_time_30blocks": None,
            "last_block_age": None,
            "masternode_enabled": 0,
            "masternode_total": 0,
            "masternode_upgraded_enabled": 0,
            "masternode_legacy_enabled": 0,
            "masternode_unknown_enabled": 0,
            "masternode_versions": [],
            "upgrade_ratio": 0.0,
            "target_version": self.settings.target_version,
            "rpc_local_status": "ok",
            "rpc_fail_streak": 0,
            "last_rpc_success_time": None,
            "cooldown_remaining_seconds": 0,
            "fork": {
                "fork_height": self.settings.fork_height,
                "current_height": None,
                "countdown_blocks": None,
                "blocks_remaining": None,
                "remaining_blocks": None,
                "estimated_eta_seconds": None,
                "state": "ERROR",
                "hoohash_bit": self.settings.hoohash_bit,
                "xelis_bit": self.settings.xelis_bit,
                "upgrade_ratio": 0.0,
                "target_version": self.settings.target_version,
                "activation_seen": False,
                "activation_height_seen": None,
                "readiness_level": "normal",
                "readiness_reasons": [],
                "stall_level": "normal",
                "last_block_age": None,
                "suspicious_blocks": [],
                "invalid_version_blocks": [],
            },
            "alerts": [],
            "recent_blocks": [],
            "recent_hashrate": [],
            "recent_block_intervals": [],
            "comparison_results": [],
            "source_health": {},
            "peers": {"summary": {}, "items": []},
            "services": {
                "summary": {
                    "overall_status": "unknown",
                    "ok_count": 0,
                    "degraded_count": 0,
                    "down_count": 0,
                    "core_sources_ok": 0,
                    "public_sites_ok": 0,
                },
                "core_sources": {},
                "public_sites": [],
                "mining_pool_summary": {
                    "total_pools": 0,
                    "reachable_pools": 0,
                    "healthy_stratum_pools": 0,
                    "up_count": 0,
                    "degraded_count": 0,
                    "down_count": 0,
                },
                "mining_pools": [],
            },
            "freshness": {
                "snapshot_age_seconds": None,
                "mn_cache_age_seconds": None,
                "masternode_list_age_seconds": None,
                "site_status_age_seconds": None,
                "site_checks_age_seconds": None,
                "daemon_data_age_seconds": None,
                "explorer_data_age_seconds": None,
                "last_block_age_seconds": None,
                "snapshot_status": "normal",
                "mn_cache_status": "normal",
                "site_status_status": "normal",
                "daemon_status": "normal",
                "explorer_status": "normal",
                "last_block_status": "normal",
                "overall_status": "normal",
                "status": "normal",
                "thresholds": self._freshness_thresholds(),
            },
            "upgrade_summary": {
                "enabled": 0,
                "upgraded": 0,
                "legacy": 0,
                "unknown": 0,
                "ratio": 0.0,
                "classification_status": "unknown",
            },
            "recent_anomalies": {
                "window_hours": 24,
                "raised_count": 0,
                "cleared_count": 0,
                "active_critical_count": 0,
                "latest": [],
            },
            "_peerinfo_raw": [],
            "_public_mempool": None,
            "_mempool_zero_started_at": None,
            "_mempool_zero_height": None,
            "_site_checks_generated_at": None,
            "_site_checks_generated_at_unix": None,
            "_masternode_cache_generated_at": None,
            "_masternode_cache_generated_at_unix": None,
            "_masternode_summary_fingerprint": None,
            "_services_generated_at_unix": None,
            "_recent_anomalies_generated_at_unix": None,
        }

    def _coerce_masternode_versions(self, payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            values: list[dict[str, Any]] = []
            for entry in payload:
                if not isinstance(entry, dict):
                    continue
                semver = entry.get("semver")
                if is_probable_ip_semver_noise(semver):
                    semver = None
                values.append(
                    {
                        **entry,
                        "semver": semver,
                    }
                )
            return values
        if isinstance(payload, dict):
            values: list[dict[str, Any]] = []
            for key, count in payload.items():
                values.append(
                    {
                        "protocol_version": None,
                        "display_version": str(key),
                        "semver": None,
                        "count": int(count),
                        "is_upgraded": None,
                    }
                )
            return values
        return []

    def _snapshot(self) -> dict[str, Any]:
        snapshot = self.cache.get_json("monitor:latest", self._latest_snapshot)
        if snapshot is None:
            snapshot = self._empty_snapshot()
        return self._apply_live_snapshot_age(snapshot, int(time.time()))

    def get_status_payload(self) -> dict[str, Any]:
        return self._snapshot()

    def get_masternodes_payload(self) -> dict[str, Any]:
        snapshot = self._snapshot()
        masternodes = self.cache.get_json(self._MASTERNODES_CACHE_KEY, {}) or {}
        return {
            "generated_at": snapshot.get("generated_at"),
            "generated_at_unix": snapshot.get("generated_at_unix"),
            "stale": snapshot.get("stale", True),
            "list_generated_at": snapshot.get("_masternode_cache_generated_at") or masternodes.get("generated_at"),
            "list_generated_at_unix": snapshot.get("_masternode_cache_generated_at_unix") or masternodes.get("generated_at_unix"),
            "items": masternodes.get("items", []),
        }

    def get_fork_payload(self) -> dict[str, Any]:
        snapshot = self._snapshot()
        return {
            "generated_at": snapshot.get("generated_at"),
            "stale": snapshot.get("stale", True),
            "fork": snapshot.get("fork", {}),
            "alerts": [
                alert
                for alert in snapshot.get("alerts", [])
                if alert["type"] in {"chain_split", "pre_fork_activation_attempt", "low_upgrade_ratio_near_fork"}
            ],
        }

    def get_hashrate_payload(self) -> dict[str, Any]:
        snapshot = self._snapshot()
        return {
            "generated_at": snapshot.get("generated_at"),
            "stale": snapshot.get("stale", True),
            "hashrate_hps": snapshot.get("hashrate_hps"),
            "hashrate_display": snapshot.get("hashrate_display"),
            "recent_hashrate": snapshot.get("recent_hashrate", []),
            "source_health": snapshot.get("source_health", {}),
        }

    def get_peers_payload(self) -> dict[str, Any]:
        snapshot = self._snapshot()
        return {
            "generated_at": snapshot.get("generated_at"),
            "stale": snapshot.get("stale", True),
            "summary": snapshot.get("peers", {}).get("summary", {}),
            "items": snapshot.get("peers", {}).get("items", []),
        }

    def get_recent_blocks_payload(self) -> dict[str, Any]:
        snapshot = self._snapshot()
        return {
            "generated_at": snapshot.get("generated_at"),
            "stale": snapshot.get("stale", True),
            "items": snapshot.get("recent_blocks", []),
        }

    def get_alerts_payload(self) -> dict[str, Any]:
        snapshot = self._snapshot()
        return {
            "generated_at": snapshot.get("generated_at"),
            "stale": snapshot.get("stale", True),
            "active": snapshot.get("alerts", []),
            "recent": self.cache.get_json("monitor:alerts:recent", []),
        }

    def get_health_payload(self) -> dict[str, Any]:
        snapshot = self._snapshot()
        source_health = snapshot.get("source_health", {})
        statuses = {
            "rpc_local": source_health.get("rpc_local", {}).get("status", "unknown"),
            "explorer_local": source_health.get("explorer_local", {}).get("status", "unknown"),
            "public_api_remote": source_health.get("public_api_remote", {}).get("status", "unknown"),
        }
        overall = "ok"
        if snapshot.get("stale") or statuses["rpc_local"] == "cooldown":
            overall = "degraded"
        if statuses["explorer_local"] in {"down"} and statuses["public_api_remote"] in {"down"}:
            overall = "degraded"
        return {
            "status": overall,
            "cache": self.cache.name,
            "sources": statuses,
        }
