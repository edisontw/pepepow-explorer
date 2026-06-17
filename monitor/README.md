# PEPEPOW Monitor

Standalone FastAPI sidecar for `explorer.pepepow.net/monitor`.

PEPEPOW core reference:

- `https://github.com/MattF42/PePe-core/`

Related docs:

- `README.md`
- `monitor_ARCHITECTURE.md`

## What it does

- polls local daemon RPC, local explorer HTTP, remote public API, and a small set of public PEPEPOW web properties
- probes selected PEPEPOW mining pool stratum endpoints with short-lived TCP connections
- normalizes source data into one cache-backed snapshot
- exposes a dashboard and JSON API under `/monitor`
- tracks fork readiness, services health, upgrade status, recent anomalies, and freshness/age signals
- keeps browser requests cheap by serving cached state instead of triggering upstream fetches

## Source topology

- local daemon RPC: `127.0.0.1:12345`
- local explorer: `127.0.0.1:3001`
- remote public API: `https://api.pepepow.net`
- public site checks:
  - `https://pepepow.org`
  - `https://explorer.pepepow.org`
  - `https://explorer.pepepow.net`
  - `https://wallet.pepepow.net`
- mining pool checks:
  - `(zpool) stratum+tcp://hoohash-pepew.eu.mine.zpool.ca:8335`
  - `(M4P) eu.mining4people.com:4176`
  - `(M4P) us-west.mining4people.com:4176`
  - `(foztor) stratum-eu.pepepow.foztor.net:13232`

The monitor uses local loopback for same-host explorer access. It does not call the public explorer domain from inside the host for core explorer data.

## Runtime model

The monitor is snapshot-driven:

- one in-process scheduler collects and normalizes upstream data
- derived data is written into `monitor:latest`
- API handlers read cached snapshot state
- the dashboard polls cached endpoints only

Current front-end polling defaults:

- `/monitor/api/status`: every `10s`
- `/monitor/api/masternodes`: every `30s`

This is intentionally slower than the internal collector loop to reduce avoidable browser-driven load.

## Required configuration

Set these environment variables before starting the service:

```bash
export MONITOR_FORK_HEIGHT=4354200
export MONITOR_HOOHASH_BIT=0x4000
export MONITOR_XELIS_BIT=0x8000
export MONITOR_MIN_UPGRADED_SUBVER=2.9.0.2
```

Optional overrides:

```bash
export MONITOR_RPC_URL=http://127.0.0.1:12345
export MONITOR_RPC_USERNAME=pepepowuser
export MONITOR_RPC_PASSWORD=
export MONITOR_EXPLORER_BASE_URL=http://127.0.0.1:3001
export MONITOR_PUBLIC_API_BASE_URL=https://api.pepepow.net
export MONITOR_REDIS_URL=redis://127.0.0.1:6379/0
export MONITOR_POLL_INTERVAL_SECONDS=5
export MONITOR_RPC_TIMEOUT=2
export MONITOR_RPC_MAX_CONNECTIONS=2
export MONITOR_REQUEST_RETRIES=0
export MONITOR_RPC_COOLDOWN_SECONDS=60
export MONITOR_RPC_FAIL_THRESHOLD=3
export MONITOR_RPC_BLOCKCOUNT_POLL_INTERVAL_SECONDS=15
export MONITOR_PEER_POLL_INTERVAL_SECONDS=180
export MONITOR_HASHRATE_POLL_INTERVAL_SECONDS=180
export MONITOR_MASTERNODE_INTERVAL_SECONDS=60
export MONITOR_SITE_STATUS_INTERVAL_SECONDS=3600
export MONITOR_MINING_POOL_INTERVAL_SECONDS=90
export MONITOR_RECENT_BLOCK_WINDOW=240
export MONITOR_BLOCK_FETCH_CONCURRENCY=8
export MONITOR_BLOCK_FETCH_LIMIT_PER_CYCLE=24
export MONITOR_BLOCK_HISTORY_COLD_START_LIMIT=1
export MONITOR_COMPARISON_SOURCES='[{"name":"remote-explorer-1","type":"explorer_http","base_url":"https://example.com","enabled":true}]'
export MONITOR_SITE_STATUS_TARGETS='[{"name":"pepepow.org","url":"https://pepepow.org","enabled":true}]'
export MONITOR_MINING_POOL_TARGETS='[{"host":"eu.mining4people.com","port":4176,"enabled":true}]'
```

If `MONITOR_RPC_USERNAME` or `MONITOR_RPC_PASSWORD` are not set, the service falls back to wallet credentials in the local explorer `settings.json` when available.

## Install

```bash
sudo apt-get update
sudo apt-get install -y python3-pip python3-venv

cd /home/ubuntu/explorer/monitor
python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

This host does not provide `python -m ensurepip`, so use the apt bootstrap above first.

## Run

```bash
cd /home/ubuntu/explorer
. monitor/.venv/bin/activate
uvicorn monitor.app:app --host 127.0.0.1 --port 8010
```

For systemd, put runtime values in `monitor/.env`.

Current PEPEPOW fork announcement values:

```bash
MONITOR_FORK_HEIGHT=4354200
MONITOR_HOOHASH_BIT=0x4000
MONITOR_XELIS_BIT=0x8000
MONITOR_MIN_UPGRADED_SUBVER=2.9.0.2
```

## API

- `GET /monitor/api/status`
- `GET /monitor/api/masternodes`
- `GET /monitor/api/fork`
- `GET /monitor/api/hashrate`
- `GET /monitor/api/peers`
- `GET /monitor/api/blocks/recent`
- `GET /monitor/api/alerts`
- `GET /monitor/api/health`

### `GET /monitor/api/status`

Primary dashboard payload. This endpoint is intended to be cheap:

- reads the cached latest snapshot
- applies lightweight live age deltas
- does not re-fetch upstream sources
- does not rebuild masternode aggregation
- does not rescan recent alert history

Important fields:

- `avg_block_time_8m`
- `avg_block_time_5m`
  - compatibility alias populated with the same 8-minute value
- `fork`
- `services.summary`, `services.core_sources`, `services.public_sites`
- `services.mining_pool_summary`, `services.mining_pools`
- `upgrade_summary`
- `recent_anomalies`
- `freshness`

Mining pool data is scheduler-driven and cached like the rest of the snapshot. The dashboard reads these fields from `/api/status`; browser refreshes do not trigger new stratum probes.

### `freshness`

The monitor separates different kinds of age so operators can tell whether:

- the chain is actually slow
- the monitor snapshot is stale
- only the masternode cache is stale
- only public site checks are stale

Current freshness fields include:

- `snapshot_age_seconds`
- `mn_cache_age_seconds`
- `site_status_age_seconds`
- `daemon_data_age_seconds`
- `explorer_data_age_seconds`
- `last_block_age_seconds`
- `snapshot_status`
- `mn_cache_status`
- `site_status_status`
- `daemon_status`
- `explorer_status`
- `last_block_status`
- `overall_status`

Status levels:

- `normal`
- `stale`
- `critical_stale`

Interpretation guide:

- fresh snapshot + high `last_block_age_seconds`: chain may be slow or stalled
- high `snapshot_age_seconds`: monitor itself is stale
- fresh snapshot + stale `mn_cache_age_seconds`: masternode summary is old, chain data may still be fresh
- fresh snapshot + stale `site_status_age_seconds`: public site health data is old, chain data may still be fresh

### `GET /monitor/api/masternodes`

Serves the most recent normalized masternode list already collected by the scheduler. It does not trigger extra upstream RPC or explorer calls.

## Low-load behavior

Recent low-load optimizations include:

- request-path reuse:
  - `/api/status` serves cached snapshot state instead of rebuilding it
- cadence splitting:
  - fast tier for core chain state
  - slower tier for masternodes
  - hourly tier for public site checks
  - 90-second tier for mining pool stratum checks
- masternode aggregation reuse:
  - tier-B summary is fingerprinted and reused if inputs did not change
- conditional cache writes:
  - recent blocks, intervals, source health, and related derived data are written only when changed
- front-end throttling:
  - status and masternodes use different polling intervals
- front-end rerender guards:
  - charts and heavier sections skip redraw when their payload did not change

These changes are meant to reduce monitor overhead without weakening fork / services / upgrade-summary visibility.

Mining pool probing stays intentionally low-load:

- it is driven only by the scheduler
- each check uses a short-lived TCP connection
- each probe sends one minimal `mining.subscribe` JSON line
- it does not run a persistent miner session
- it does not submit shares or keep long-lived pool connections open

## Redis

Redis is optional. If `MONITOR_REDIS_URL` is not set or Redis is unreachable, the monitor uses in-memory cache.

## Deployment

See:

- `deployment/monitor.service`
- `deployment/nginx.monitor.conf`

## Troubleshooting

- If fork state is `ERROR`, confirm the four required fork env vars are set.
- If the dashboard is stale, check `/monitor/api/health` and service logs.
- If local RPC is unavailable, the service falls back to local explorer and remote API where possible, but recent block history stops advancing until RPC recovers.
- If local RPC starts causing CPU spikes, keep `monitor.service` disabled and test with manual `systemctl start`; the scheduler already enters RPC cooldown after repeated failures and skips heavier RPC methods unless their interval is due.
- Masternode version buckets classify as upgraded / legacy / unknown. Mixed evidence such as `2.9.0.x` remains `unknown` instead of being forced into legacy.
- High host CPU is not automatically a monitor problem. In recent inspection, heavier CPU consumers were mainly `PEPEPOWd`, multiple `node` processes, and `mongod`, while `uvicorn` stayed comparatively low.
