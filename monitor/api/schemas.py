from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AlertModel(BaseModel):
    id: str
    type: str
    severity: str
    title: str
    message: str
    source: str
    details: dict[str, Any] = {}
    active_since: str | None = None


class SourceHealthModel(BaseModel):
    name: str
    kind: str
    status: str
    latency_ms: float | None = None
    last_success_at: str | None = None
    last_error: str | None = None
    consecutive_failures: int = 0
    cooldown_remaining_seconds: int = 0


class SiteStatusModel(BaseModel):
    name: str
    url: str
    status: str
    status_code: int | None = None
    latency_ms: float | None = None
    last_checked_at: str | None = None
    last_success_at: str | None = None
    last_error: str | None = None
    consecutive_failures: int = 0


class MiningPoolStatusModel(BaseModel):
    endpoint: str
    host: str
    port: int
    tcp_connect_ok: bool = False
    stratum_ok: bool = False
    latency_ms: float | None = None
    checked_at: str | None = None
    last_ok_at: str | None = None
    status: str = "down"
    error: str | None = None


class MiningPoolSummaryModel(BaseModel):
    total_pools: int = 0
    reachable_pools: int = 0
    healthy_stratum_pools: int = 0
    up_count: int = 0
    degraded_count: int = 0
    down_count: int = 0


class ServicesSummaryModel(BaseModel):
    overall_status: str = "unknown"
    ok_count: int = 0
    degraded_count: int = 0
    down_count: int = 0
    core_sources_ok: int = 0
    public_sites_ok: int = 0


class ServicesModel(BaseModel):
    summary: ServicesSummaryModel = Field(default_factory=ServicesSummaryModel)
    core_sources: dict[str, SourceHealthModel] = Field(default_factory=dict)
    public_sites: list[SiteStatusModel] = Field(default_factory=list)
    mining_pool_summary: MiningPoolSummaryModel = Field(default_factory=MiningPoolSummaryModel)
    mining_pools: list[MiningPoolStatusModel] = Field(default_factory=list)


class FreshnessModel(BaseModel):
    snapshot_age_seconds: int | None = None
    mn_cache_age_seconds: int | None = None
    masternode_list_age_seconds: int | None = None
    site_status_age_seconds: int | None = None
    site_checks_age_seconds: int | None = None
    daemon_data_age_seconds: int | None = None
    explorer_data_age_seconds: int | None = None
    last_block_age_seconds: int | None = None
    snapshot_status: str = "normal"
    mn_cache_status: str = "normal"
    site_status_status: str = "normal"
    daemon_status: str = "normal"
    explorer_status: str = "normal"
    last_block_status: str = "normal"
    overall_status: str = "normal"
    status: str = "normal"
    thresholds: dict[str, dict[str, int]] = Field(default_factory=dict)


class UpgradeSummaryModel(BaseModel):
    enabled: int = 0
    upgraded: int = 0
    legacy: int = 0
    unknown: int = 0
    ratio: float = 0.0
    classification_status: str = "unknown"


class RecentAnomaliesModel(BaseModel):
    window_hours: int = 24
    raised_count: int = 0
    cleared_count: int = 0
    active_critical_count: int = 0
    latest: list[dict[str, Any]] = Field(default_factory=list)


class MasternodeVersionModel(BaseModel):
    protocol_version: int | None = None
    display_version: str
    semver: str | None = None
    count: int
    is_upgraded: bool | None = None


class MasternodeItemModel(BaseModel):
    addr: str | None = None
    txid: str | None = None
    ip: str | None = None
    status: str | None = None
    lastseen: int | None = None
    activetime: int | None = None
    version: int | None = None
    subver: str | None = None
    fallback_only: bool = False


class MasternodesPayloadModel(BaseModel):
    generated_at: str | None = None
    generated_at_unix: int | None = None
    stale: bool = True
    list_generated_at: str | None = None
    list_generated_at_unix: int | None = None
    items: list[MasternodeItemModel] = Field(default_factory=list)


class RewardEstimateModel(BaseModel):
    block_reward: float | None = None
    enabled_masternodes: int = 0
    per_20s: float | None = None
    per_hour: float | None = None
    per_day: float | None = None
    formula: str = "block_reward * 0.95 * 0.35 / enabled_masternodes"


class StatusModel(BaseModel):
    generated_at: str | None = None
    generated_at_unix: int | None = None
    stale: bool = True
    height: int | None = None
    height_source: str | None = None
    local_hash: str | None = None
    hashrate_hps: float | None = None
    hashrate_display: str | None = None
    difficulty: float | None = None
    peer_count: int = 0
    mempool_txs: int | None = None
    mempool_size: int | None = None
    mempool_bytes: int | None = None
    mempool_zero_duration: int = 0
    avg_block_time_3m: float | None = None
    avg_block_time_5m: float | None = None
    avg_block_time_8m: float | None = None
    avg_block_time_30m: float | None = None
    avg_block_time_2h: float | None = None
    avg_block_time_30blocks: float | None = None
    last_block_age: int | None = None
    masternode_enabled: int = 0
    masternode_total: int = 0
    masternode_upgraded_enabled: int = 0
    masternode_legacy_enabled: int = 0
    masternode_unknown_enabled: int = 0
    masternode_versions: list[MasternodeVersionModel] = []
    upgrade_ratio: float = 0.0
    target_version: str | None = None
    rpc_local_status: str = "ok"
    rpc_fail_streak: int = 0
    last_rpc_success_time: str | None = None
    cooldown_remaining_seconds: int = 0
    fork: dict[str, Any] = Field(default_factory=dict)
    alerts: list[AlertModel] = Field(default_factory=list)
    recent_blocks: list[dict[str, Any]] = Field(default_factory=list)
    recent_hashrate: list[dict[str, Any]] = Field(default_factory=list)
    recent_block_intervals: list[dict[str, Any]] = Field(default_factory=list)
    comparison_results: list[dict[str, Any]] = Field(default_factory=list)
    source_health: dict[str, SourceHealthModel] = Field(default_factory=dict)
    peers: dict[str, Any] = Field(default_factory=dict)
    services: ServicesModel = Field(default_factory=ServicesModel)
    freshness: FreshnessModel = Field(default_factory=FreshnessModel)
    upgrade_summary: UpgradeSummaryModel = Field(default_factory=UpgradeSummaryModel)
    recent_anomalies: RecentAnomaliesModel = Field(default_factory=RecentAnomaliesModel)
    reward_estimate: RewardEstimateModel = Field(default_factory=RewardEstimateModel)


class HealthModel(BaseModel):
    status: str
    cache: str
    sources: dict[str, str]
