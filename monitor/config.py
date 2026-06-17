from __future__ import annotations

import os
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

import json5


def _strip_json_comments(text: str) -> str:
    out: list[str] = []
    in_string = False
    escaped = False
    in_line_comment = False
    in_block_comment = False
    index = 0

    while index < len(text):
        char = text[index]
        next_char = text[index + 1] if index + 1 < len(text) else ""

        if in_line_comment:
            if char == "\n":
                in_line_comment = False
                out.append(char)
            index += 1
            continue

        if in_block_comment:
            if char == "*" and next_char == "/":
                in_block_comment = False
                index += 2
            else:
                index += 1
            continue

        if char == '"' and not escaped:
            in_string = not in_string
            out.append(char)
            index += 1
            escaped = False
            continue

        if not in_string and char == "/" and next_char == "/":
            in_line_comment = True
            index += 2
            continue

        if not in_string and char == "/" and next_char == "*":
            in_block_comment = True
            index += 2
            continue

        out.append(char)
        escaped = char == "\\" and not escaped
        if char != "\\":
            escaped = False
        index += 1

    return "".join(out)


def _parse_settings_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json5.loads(_strip_json_comments(path.read_text(encoding="utf-8")))


def _env_int(name: str, default: int | None = None) -> int | None:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return int(value, 0)


def _sanitize_url(url: str) -> tuple[str, str | None, str | None]:
    parsed = urlparse(url)
    username = parsed.username
    password = parsed.password
    if username is None and password is None:
        return url, None, None

    netloc = parsed.hostname or ""
    if parsed.port is not None:
        netloc = f"{netloc}:{parsed.port}"

    sanitized = urlunparse(
        (
            parsed.scheme,
            netloc,
            parsed.path,
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    )
    return sanitized, username, password


def _parse_rpc_command(value: str | None, default_method: str) -> tuple[str, tuple[Any, ...]]:
    if not value:
        return default_method, ()
    parts = shlex.split(str(value))
    if not parts:
        return default_method, ()

    method = parts[0]
    params: list[Any] = []
    for item in parts[1:]:
        try:
            params.append(int(item, 0))
        except ValueError:
            params.append(item)
    return method, tuple(params)


@dataclass(slots=True)
class ComparisonSource:
    name: str
    type: str
    base_url: str | None = None
    rpc_url: str | None = None
    username: str | None = None
    password: str | None = None
    enabled: bool = True


@dataclass(slots=True)
class SiteStatusTarget:
    name: str
    url: str
    enabled: bool = True


@dataclass(slots=True)
class MiningPoolTarget:
    host: str
    port: int
    name: str | None = None
    enabled: bool = True


@dataclass(slots=True)
class Settings:
    repo_root: Path
    title: str
    root_path: str
    rpc_url: str
    rpc_username: str | None
    rpc_password: str | None
    explorer_base_url: str
    public_api_base_url: str
    redis_url: str | None
    poll_interval_seconds: int
    rpc_timeout_seconds: float
    request_connect_timeout_seconds: float
    request_read_timeout_seconds: float
    request_retries: int
    request_retry_backoff_seconds: tuple[float, ...]
    rpc_max_connections: int
    rpc_max_keepalive_connections: int
    rpc_failure_cooldown_seconds: int
    rpc_fail_threshold: int
    rpc_blockcount_poll_interval_seconds: int
    masternode_interval_seconds: int
    peerinfo_interval_seconds: int
    hashrate_poll_interval_seconds: int
    site_status_interval_seconds: int
    mining_pool_interval_seconds: int
    block_fetch_concurrency: int
    block_fetch_limit_per_cycle: int
    block_history_cold_start_limit: int
    recent_block_window: int
    alert_window_blocks: int
    block_target_seconds: int
    rate_limit_rpm: int
    fork_height: int | None
    hoohash_bit: int | None
    xelis_bit: int | None
    min_upgraded_subver: str | None
    target_version: str
    masternode_count_rpc_method: str
    masternode_count_rpc_params: tuple[Any, ...]
    masternode_list_rpc_method: str
    masternode_list_rpc_params: tuple[Any, ...]
    comparison_sources: list[ComparisonSource] = field(default_factory=list)
    site_status_targets: list[SiteStatusTarget] = field(default_factory=list)
    mining_pool_targets: list[MiningPoolTarget] = field(default_factory=list)
    split_match_clear_polls: int = 3
    source_failure_threshold: int = 3
    stale_after_seconds: int = 15
    difficulty_anomaly_ratio: float = 3.0
    interval_low_ratio: float = 0.5
    interval_high_ratio: float = 2.5
    monitor_block_reward: float | None = None

    @property
    def fork_configured(self) -> bool:
        return (
            self.fork_height is not None
            and self.hoohash_bit is not None
            and self.xelis_bit is not None
            and bool(self.min_upgraded_subver)
        )


def load_settings() -> Settings:
    repo_root = Path(__file__).resolve().parents[1]
    explorer_settings = _parse_settings_file(repo_root / "settings.json")
    wallet = explorer_settings.get("wallet", {})
    webserver = explorer_settings.get("webserver", {})

    rpc_default = f"http://{wallet.get('host', '127.0.0.1')}:{wallet.get('port', 12345)}"
    rpc_url_raw = os.getenv("MONITOR_RPC_URL", rpc_default)
    rpc_url, rpc_user_from_url, rpc_pass_from_url = _sanitize_url(rpc_url_raw)

    explorer_port = webserver.get("port", 3001)
    api_cmds = explorer_settings.get("api_cmds", {})
    masternode_count_rpc_method, masternode_count_rpc_params = _parse_rpc_command(
        api_cmds.get("getmasternodecount"),
        "getmasternodecount",
    )
    masternode_list_rpc_method, masternode_list_rpc_params = _parse_rpc_command(
        api_cmds.get("getmasternodelist"),
        "getmasternodelist",
    )
    comparison_sources: list[ComparisonSource] = []
    comparison_raw = os.getenv("MONITOR_COMPARISON_SOURCES", "[]")
    try:
        comparison_payload = json5.loads(comparison_raw)
    except ValueError:
        comparison_payload = []

    for item in comparison_payload:
        if not isinstance(item, dict):
            continue
        comparison_sources.append(
            ComparisonSource(
                name=str(item.get("name", "unnamed-source")),
                type=str(item.get("type", "explorer_http")),
                base_url=item.get("base_url"),
                rpc_url=item.get("rpc_url"),
                username=item.get("username"),
                password=item.get("password"),
                enabled=bool(item.get("enabled", True)),
            )
        )

    site_status_targets = [
        SiteStatusTarget(name="pepepow.org", url="https://pepepow.org"),
        SiteStatusTarget(name="explorer.pepepow.org", url="https://explorer.pepepow.org"),
        SiteStatusTarget(name="explorer.pepepow.net", url="https://explorer.pepepow.net"),
        SiteStatusTarget(name="wallet.pepepow.net", url="https://wallet.pepepow.net"),
    ]
    site_targets_raw = os.getenv("MONITOR_SITE_STATUS_TARGETS")
    if site_targets_raw:
        try:
            site_payload = json5.loads(site_targets_raw)
        except ValueError:
            site_payload = []
        parsed_targets: list[SiteStatusTarget] = []
        for item in site_payload:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url", "")).strip()
            if not url:
                continue
            parsed_targets.append(
                SiteStatusTarget(
                    name=str(item.get("name") or urlparse(url).netloc or url),
                    url=url,
                    enabled=bool(item.get("enabled", True)),
                )
            )
        if parsed_targets:
            site_status_targets = parsed_targets

    mining_pool_targets = [
        MiningPoolTarget(host="hoohash-pepew.eu.mine.zpool.ca", port=8335, name="(zpool) stratum+tcp://hoohash-pepew.eu.mine.zpool.ca:8335"),
        MiningPoolTarget(host="eu.mining4people.com", port=4176, name="(M4P) eu.mining4people.com:4176"),
        MiningPoolTarget(host="us-west.mining4people.com", port=4176, name="(M4P) us-west.mining4people.com:4176"),
        MiningPoolTarget(host="stratum-eu.pepepow.foztor.net", port=13232, name="(foztor) stratum-eu.pepepow.foztor.net:13232"),
        MiningPoolTarget(host="pool.pepepow.net", port=39333, name="Lab — pool.pepepow.net:39333"),
    ]
    mining_pools_raw = os.getenv("MONITOR_MINING_POOL_TARGETS")
    if mining_pools_raw:
        try:
            mining_pool_payload = json5.loads(mining_pools_raw)
        except ValueError:
            mining_pool_payload = []
        parsed_pool_targets: list[MiningPoolTarget] = []
        for item in mining_pool_payload:
            if not isinstance(item, dict):
                continue
            host = str(item.get("host", "")).strip()
            if not host:
                continue
            try:
                port = int(item.get("port"))
            except (TypeError, ValueError):
                port = None
            if port is None or port <= 0:
                continue
            parsed_pool_targets.append(
                MiningPoolTarget(
                    host=host,
                    port=port,
                    name=item.get("name"),
                    enabled=bool(item.get("enabled", True)),
                )
            )
        if parsed_pool_targets:
            mining_pool_targets = parsed_pool_targets

    poll_interval = _env_int("MONITOR_POLL_INTERVAL_SECONDS", 5) or 5
    request_retries = _env_int("MONITOR_REQUEST_RETRIES")
    if request_retries is None:
        request_retries = 2
    rpc_timeout = float(os.getenv("MONITOR_RPC_TIMEOUT", os.getenv("MONITOR_READ_TIMEOUT_SECONDS", "2")))
    rpc_connect_timeout = float(os.getenv("MONITOR_CONNECT_TIMEOUT_SECONDS", str(min(rpc_timeout, 1.0))))
    rpc_read_timeout = float(os.getenv("MONITOR_READ_TIMEOUT_SECONDS", str(rpc_timeout)))
    rpc_cooldown_seconds = _env_int(
        "MONITOR_RPC_COOLDOWN_SECONDS",
        _env_int("MONITOR_RPC_FAILURE_COOLDOWN_SECONDS", 60),
    ) or 60
    target_version = os.getenv("MONITOR_MIN_UPGRADED_SUBVER", "2.9.0.2")

    block_reward_val = os.getenv("MONITOR_BLOCK_REWARD", "7000")
    monitor_block_reward = 7000.0
    if block_reward_val and block_reward_val.strip():
        try:
            monitor_block_reward = float(block_reward_val)
        except ValueError:
            monitor_block_reward = 7000.0

    return Settings(
        repo_root=repo_root,
        monitor_block_reward=monitor_block_reward,
        title=os.getenv("MONITOR_TITLE", "PEPEPOW Network Monitor"),
        root_path=os.getenv("MONITOR_ROOT_PATH", "/monitor"),
        rpc_url=rpc_url,
        rpc_username=os.getenv("MONITOR_RPC_USERNAME") or rpc_user_from_url or wallet.get("username"),
        rpc_password=os.getenv("MONITOR_RPC_PASSWORD") or rpc_pass_from_url or wallet.get("password"),
        explorer_base_url=os.getenv("MONITOR_EXPLORER_BASE_URL", f"http://127.0.0.1:{explorer_port}").rstrip("/"),
        public_api_base_url=os.getenv("MONITOR_PUBLIC_API_BASE_URL", "https://api.pepepow.net").rstrip("/"),
        redis_url=os.getenv("MONITOR_REDIS_URL"),
        poll_interval_seconds=poll_interval,
        rpc_timeout_seconds=rpc_timeout,
        request_connect_timeout_seconds=rpc_connect_timeout,
        request_read_timeout_seconds=rpc_read_timeout,
        request_retries=max(request_retries, 0),
        request_retry_backoff_seconds=(0.25, 0.75),
        rpc_max_connections=max(_env_int("MONITOR_RPC_MAX_CONNECTIONS", 2) or 2, 1),
        rpc_max_keepalive_connections=max(_env_int("MONITOR_RPC_MAX_KEEPALIVE_CONNECTIONS", 1) or 1, 1),
        rpc_failure_cooldown_seconds=max(rpc_cooldown_seconds, 1),
        rpc_fail_threshold=max(_env_int("MONITOR_RPC_FAIL_THRESHOLD", 3) or 3, 1),
        rpc_blockcount_poll_interval_seconds=max(_env_int("MONITOR_RPC_BLOCKCOUNT_POLL_INTERVAL_SECONDS", 15) or 15, 1),
        masternode_interval_seconds=max(_env_int("MONITOR_MASTERNODE_INTERVAL_SECONDS", 60) or 60, 1),
        peerinfo_interval_seconds=max(
            _env_int("MONITOR_PEERINFO_INTERVAL_SECONDS", _env_int("MONITOR_PEER_POLL_INTERVAL_SECONDS", 180)) or 180,
            1,
        ),
        hashrate_poll_interval_seconds=max(
            _env_int("MONITOR_HASHRATE_INTERVAL_SECONDS", _env_int("MONITOR_HASHRATE_POLL_INTERVAL_SECONDS", 180)) or 180,
            1,
        ),
        site_status_interval_seconds=max(_env_int("MONITOR_SITE_STATUS_INTERVAL_SECONDS", 3600) or 3600, 60),
        mining_pool_interval_seconds=max(_env_int("MONITOR_MINING_POOL_INTERVAL_SECONDS", 90) or 90, 60),
        block_fetch_concurrency=max(_env_int("MONITOR_BLOCK_FETCH_CONCURRENCY", 8) or 8, 1),
        block_fetch_limit_per_cycle=max(_env_int("MONITOR_BLOCK_FETCH_LIMIT_PER_CYCLE", 24) or 24, 1),
        block_history_cold_start_limit=max(_env_int("MONITOR_BLOCK_HISTORY_COLD_START_LIMIT", 1) or 1, 1),
        recent_block_window=_env_int("MONITOR_RECENT_BLOCK_WINDOW", 240) or 240,
        alert_window_blocks=_env_int("MONITOR_ALERT_WINDOW_BLOCKS", 120) or 120,
        block_target_seconds=_env_int("MONITOR_BLOCK_TARGET_SECONDS", 60) or 60,
        rate_limit_rpm=_env_int("MONITOR_RATE_LIMIT_RPM", 60) or 60,
        fork_height=_env_int("MONITOR_FORK_HEIGHT"),
        hoohash_bit=_env_int("MONITOR_HOOHASH_BIT"),
        xelis_bit=_env_int("MONITOR_XELIS_BIT"),
        min_upgraded_subver=os.getenv("MONITOR_MIN_UPGRADED_SUBVER") or target_version,
        target_version=target_version,
        masternode_count_rpc_method=masternode_count_rpc_method,
        masternode_count_rpc_params=masternode_count_rpc_params,
        masternode_list_rpc_method=masternode_list_rpc_method,
        masternode_list_rpc_params=masternode_list_rpc_params,
        comparison_sources=comparison_sources,
        site_status_targets=site_status_targets,
        mining_pool_targets=mining_pool_targets,
        stale_after_seconds=max(poll_interval * 12, 120),
    )
