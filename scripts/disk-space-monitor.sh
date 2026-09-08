#!/usr/bin/env bash
set -euo pipefail

MOUNT_POINT="/"
USAGE_LINE=$(df -k "$MOUNT_POINT" | tail -n 1)
TOTAL_KB=$(echo "$USAGE_LINE" | awk '{print $2}')
USED_KB=$(echo "$USAGE_LINE" | awk '{print $3}')
AVAIL_KB=$(echo "$USAGE_LINE" | awk '{print $4}')
USE_PCT=$(echo "$USAGE_LINE" | awk '{print $5}' | tr -d '%')

TOTAL_GB=$(awk -v t="$TOTAL_KB" 'BEGIN {printf "%.1f", t/1048576}')
USED_GB=$(awk -v u="$USED_KB" 'BEGIN {printf "%.1f", u/1048576}')
AVAIL_GB=$(awk -v a="$AVAIL_KB" 'BEGIN {printf "%.1f", a/1048576}')

STATUS="OK"

if [ "$USE_PCT" -ge 90 ] || [ "$AVAIL_KB" -lt 3145728 ]; then
    STATUS="CRITICAL"
    logger -t disk-space-monitor -p user.crit "CRITICAL: Root disk usage is at ${USE_PCT}% (${AVAIL_GB}GB / ${TOTAL_GB}GB free). Emergency threshold reached."
    
    # Emergency log cleanup if space is critically low (<2GB)
    if [ "$AVAIL_KB" -lt 2097152 ]; then
        logger -t disk-space-monitor -p user.crit "EMERGENCY: Free space below 2GB! Executing emergency log vacuuming."
        journalctl --vacuum-size=100M >/dev/null 2>&1 || true
        /usr/sbin/logrotate -f /etc/logrotate.d/nginx >/dev/null 2>&1 || true
        /usr/sbin/logrotate -f /etc/logrotate.d/pepepow >/dev/null 2>&1 || true
    fi
elif [ "$USE_PCT" -ge 80 ]; then
    STATUS="WARNING"
    logger -t disk-space-monitor -p user.warning "WARNING: Root disk usage is at ${USE_PCT}% (${AVAIL_GB}GB / ${TOTAL_GB}GB free)."
else
    STATUS="OK"
fi

STATUS_FILE="/run/disk-status.json"
NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)

cat > "$STATUS_FILE" << JSON_EOF
{
  "timestamp": "$NOW",
  "mount": "$MOUNT_POINT",
  "status": "$STATUS",
  "use_percent": $USE_PCT,
  "used_gb": $USED_GB,
  "avail_gb": $AVAIL_GB,
  "total_gb": $TOTAL_GB
}
JSON_EOF
chmod 644 "$STATUS_FILE" 2>/dev/null || true

echo "Disk Check: status=$STATUS, use=${USE_PCT}%, used=${USED_GB}GB, free=${AVAIL_GB}GB, total=${TOTAL_GB}GB"
