#!/bin/bash
set -u

REPO_DIR="/home/ubuntu/explorer"
LOCK_DIR="/tmp/explorer-sync.lock"

cd "$REPO_DIR" || exit 1

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    echo "[$(date -Is)] sync.sh is already running; exiting"
    exit 1
fi

cleanup() {
    rmdir "$LOCK_DIR" 2>/dev/null || true
}

trap cleanup EXIT INT TERM

run_task() {
    local label="$1"
    shift

    echo "[$(date -Is)] starting ${label}"
    "$@"
    local status=$?
    echo "[$(date -Is)] finished ${label} status=${status}"
    return $status
}

BLOCKS_INTERVAL=30
PEERS_INTERVAL=120
MARKETS_INTERVAL=900
MASTERNODES_INTERVAL=600
LOOP_SLEEP=15

last_blocks_run=0
last_peers_run=0
last_markets_run=0
last_masternodes_run=0

while true; do
    now=$(date +%s)

    if (( now - last_blocks_run >= BLOCKS_INTERVAL )); then
        run_task "sync-blocks" npm run sync-blocks
        last_blocks_run=$now
    fi

    if (( now - last_peers_run >= PEERS_INTERVAL )); then
        run_task "sync-peers" npm run sync-peers
        last_peers_run=$now
    fi

    if (( now - last_markets_run >= MARKETS_INTERVAL )); then
        run_task "sync-markets" npm run sync-markets
        last_markets_run=$now
    fi

    if (( now - last_masternodes_run >= MASTERNODES_INTERVAL )); then
        run_task "sync-masternodes" npm run sync-masternodes
        last_masternodes_run=$now
    fi

    sleep "$LOOP_SLEEP"
done
