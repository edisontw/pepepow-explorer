# PEPEPOW Monitor Architecture

## Purpose

PEPEPOW `/monitor` is a standalone FastAPI sidecar that provides:

- a dashboard under `/monitor`
- a JSON API under `/monitor/api/*`

Its design goals are:

- keep collection centralized
- normalize multiple upstreams into one snapshot
- make API requests cheap
- avoid heavy request-time work
- preserve fork and operator visibility without unnecessary load

## System Shape

```text
local RPC        local explorer        public API        public sites
    |                  |                  |                  |
    +------------------+------------------+------------------+
                               |
                        MonitorSources
                               |
                        MonitorCollector
                     (scheduler + caching)
                               |
                        cache-backed snapshot
                               |
                 +-------------+--------------+
                 |                            |
              JSON API                    Dashboard UI
```

## Core Modules

### `app.py`

Bootstraps the service:

- loads settings
- builds cache backend
- builds shared source clients
- creates the singleton collector
- wires FastAPI routes and static assets
- starts and stops the collector via lifespan hooks

### `config.py`

Loads runtime configuration from:

- environment variables
- explorer `settings.json`

Key settings areas:

- RPC and explorer connection info
- scheduler intervals
- fork configuration
- comparison node definitions
- public site health targets
- cache backend selection

### `collector/sources.py`

Thin async wrappers over upstream data sources:

- daemon RPC
- local explorer HTTP
- public API
- public site checks
- optional comparison nodes

This layer should stay transport-focused. It should not contain scheduling or policy logic.

### `collector/scheduler.py`

The heart of the monitor.

Responsibilities:

- run the background refresh loop
- split work by cadence
- maintain RPC cooldown behavior
- collect and normalize upstream data
- build the latest snapshot
- update secondary cache keys when needed
- serve cheap request-path payloads from cached state

This is the main place to inspect when changing monitor behavior.

### `services/aggregation.py`

Derived aggregation helpers, including:

- averages and interval series
- peer version summaries
- masternode version grouping
- masternode summary fingerprinting

### `services/detection.py`

Alerting and readiness logic, such as:

- fork readiness
- fork-adjacent stall detection
- mempool anomalies
- RPC cooldown alerts
- source degradation
- public site degradation
- comparison split alerts

### `api/routes.py` and `api/schemas.py`

Expose typed JSON responses for the dashboard and operators.

Primary endpoint:

- `GET /monitor/api/status`

This endpoint is expected to be the main dashboard payload and must remain lightweight.

### `ui/templates/dashboard.html`

Single dashboard template shell.

### `ui/static/monitor.js`

Client polling and rendering logic.

Important design rules:

- poll cached monitor endpoints only
- do not trigger upstream fetches
- avoid unnecessary rerenders when data is unchanged

### `cache/*`

Cache abstraction with:

- in-memory backend
- Redis backend

The monitor works without Redis, but Redis can help persist snapshot state outside the process.

## Snapshot-Centric Design

The monitor is built around one normalized snapshot:

- collector refresh builds `monitor:latest`
- APIs return snapshot slices
- dashboard consumes cached snapshot data

The snapshot typically includes:

- chain state
- recent blocks
- recent hashrate and interval series
- source health
- fork state
- alerts
- services summary
- upgrade summary
- recent anomalies
- freshness metadata

Rule:

- if something can be computed during scheduler refresh and stored, prefer that over request-time recomputation

## Refresh Cadence

The collector loop runs on `poll_interval_seconds`, but upstream work is split by due checks.

### Fast tier

Typical data:

- daemon block count
- local explorer block count
- public API height
- public API mempool
- recent block append/reorg handling

Goal:

- keep chain state fresh

### Medium tier

Typical data:

- peerinfo
- network hashrate
- masternode count/list normalization and summary

Goal:

- keep readiness and node-state views useful without hammering sources

### Slow tier

Typical data:

- public site checks

Goal:

- track website availability without adding high-frequency web polling

## Low-Load Strategy

The current design reduces monitor overhead through several mechanisms.

### 1. Cheap request path

`/api/status` should:

- read the latest snapshot
- apply a small live age delta
- return

It should not:

- fetch RPC or explorer on demand
- rebuild masternode summaries
- rescan recent alert history

### 2. Reuse expensive tier-B aggregation

Masternode grouping is one of the heavier monitor-side operations.

Current optimization:

- build a fingerprint from normalized tier-B inputs
- if fingerprint did not change, reuse prior:
  - masternode summary
  - upgrade summary

### 3. Conditional cache writes

Derived artifacts should only be rewritten when changed:

- recent blocks
- block intervals
- source health
- related auxiliary cache keys

This reduces:

- JSON serialization churn
- Redis round-trips
- memory copy overhead

### 4. Browser polling is treated as load too

Current dashboard defaults:

- `/api/status`: `10s`
- `/api/masternodes`: `30s`

This keeps UI reasonably fresh while avoiding needless repeated payload transfer and DOM/chart updates.

### 5. Front-end rerender guards

The dashboard tracks lightweight signatures for:

- services
- alerts
- anomalies
- peers
- masternode summary
- blocks
- comparison results
- charts

If a section payload is unchanged, that section does not rerender.

## Freshness Model

The monitor explicitly separates data ages so operators can diagnose the right problem.

### Freshness fields

Current `/api/status -> freshness` fields include:

- `snapshot_age_seconds`
- `mn_cache_age_seconds`
- `site_status_age_seconds`
- `daemon_data_age_seconds`
- `explorer_data_age_seconds`
- `last_block_age_seconds`

### Freshness status fields

- `snapshot_status`
- `mn_cache_status`
- `site_status_status`
- `daemon_status`
- `explorer_status`
- `last_block_status`
- `overall_status`

### Status values

- `normal`
- `stale`
- `critical_stale`

### Operator interpretation

- high `snapshot_age_seconds`: monitor itself is stale
- fresh snapshot + high `last_block_age_seconds`: chain may be slow or stalled
- fresh snapshot + high `mn_cache_age_seconds`: masternode summary is stale
- fresh snapshot + high `site_status_age_seconds`: public site status is stale

This split is intentional so chain issues and monitor issues are not conflated.

## Services Model

There are two related but distinct layers.

### `source_health`

Low-level per-source operational state:

- `rpc_local`
- `explorer_local`
- `public_api_remote`

### `services`

Operator-facing summary that combines:

- core source health
- public site health

This keeps transport-level details separate from dashboard-level service status.

## Fork Monitoring Path

Fork state is derived from:

- current authoritative height
- recent block samples
- configured fork height and version bits
- upgrade ratio from masternode summary

Outputs include:

- fork state
- remaining blocks
- ETA
- readiness level
- stall level
- fork alerts

Fork monitoring depends on already-collected block and summary state rather than separate heavyweight workflows.

## API Surface

Main endpoints:

- `GET /monitor/api/status`
- `GET /monitor/api/masternodes`
- `GET /monitor/api/fork`
- `GET /monitor/api/hashrate`
- `GET /monitor/api/peers`
- `GET /monitor/api/blocks/recent`
- `GET /monitor/api/alerts`
- `GET /monitor/api/health`

Design intent:

- `status` is the primary dashboard endpoint
- the other endpoints expose narrower slices of the same cached state

## Operational Notes

The monitor runs on the same host as the explorer stack, so host-level CPU issues must be interpreted carefully.

Recent inspection showed higher CPU from:

- `PEPEPOWd`
- multiple `node` processes
- `mongod`

`uvicorn` was relatively low.

That means monitor work should still be kept lean, but host CPU spikes should not automatically be attributed to the monitor process.

## Files To Read First

When changing the monitor, start here:

1. `collector/scheduler.py`
2. `services/aggregation.py`
3. `services/detection.py`
4. `api/schemas.py`
5. `ui/static/monitor.js`
6. `README.md`

## Change Guidelines

- prefer extending the snapshot over adding request-time work
- keep expensive collection cadence-separated
- reuse cache and prior summaries whenever possible
- preserve fork / services / upgrade summary behavior unless explicitly changing it
- treat browser polling as a real part of load, not just backend source polling
