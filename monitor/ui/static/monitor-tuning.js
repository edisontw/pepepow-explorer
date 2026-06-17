// Calmer public monitor presentation overrides. Loaded after monitor.js.

function alertPresentation(alert) {
  const type = alert?.type || "";
  if (type === "fork_config_error") {
    return null;
  }
  if (type === "mempool_zero" || type === "mempool_zero_recent") {
    const duration = Number(alert?.details?.duration_seconds || 0);
    if (duration && duration < 1800) {
      return null;
    }
    return {
      ...alert,
      severity: "info",
      title: "Mempool quiet",
      message: duration
        ? `Mempool has been quiet for ${formatDuration(duration)} while blocks continue.`
        : "Mempool is quiet while blocks continue.",
    };
  }
  if (type === "slow_blocks" || type === "fork_stall") {
    return {
      ...alert,
      severity: alert.severity === "critical" ? "critical" : "warning",
      title: "Block arrival delayed",
      message: "Block arrival is slower than usual. This can be normal during PEPEPOW RPC lag; monitor for persistence.",
    };
  }
  if (type === "public_site_down" || type === "public_services_down") {
    return {
      ...alert,
      severity: "warning",
      title: "Public endpoint probe failed",
      message: alert.message || "One public endpoint failed a probe. Core chain monitoring can still be healthy.",
    };
  }
  if (type === "source_down" && !["rpc_local", "explorer_local"].includes(alert.source)) {
    return {
      ...alert,
      severity: "info",
      title: "Secondary data source unavailable",
      message: alert.message || "A secondary data source is temporarily unavailable.",
    };
  }
  return alert;
}

function activeAlertList(alerts) {
  const seen = new Set();
  return (alerts || [])
    .map(alertPresentation)
    .filter(Boolean)
    .filter((alert) => {
      const key = `${alert.type || "alert"}:${alert.source || "monitor"}:${alert.title || ""}`;
      if (seen.has(key)) {
        return false;
      }
      seen.add(key);
      return true;
    })
    .slice(0, 5);
}

function renderAlerts(alerts) {
  const list = byId("alerts-list");
  if (!list) {
    return;
  }
  list.innerHTML = "";
  const visibleAlerts = activeAlertList(alerts);
  if (!visibleAlerts.length) {
    const item = document.createElement("li");
    item.className = "alert-item info";
    item.textContent = "No active chain alerts.";
    list.appendChild(item);
    return;
  }

  visibleAlerts.forEach((alert) => {
    const item = document.createElement("li");
    item.className = `alert-item ${escapeHtml(alert.severity || "info")}`;
    item.innerHTML = `<strong>${escapeHtml(alert.title || "Alert")}</strong><div>${escapeHtml(alert.message || "")}</div>`;
    list.appendChild(item);
  });
}

function renderAnomalySummary(anomalies) {
  const container = byId("anomaly-summary");
  if (!container) {
    return;
  }
  const raised = Number(anomalies?.raised_count || 0);
  const cleared = Number(anomalies?.cleared_count || 0);
  const critical = Number(anomalies?.active_critical_count || 0);
  const latest = (anomalies?.latest || []).slice(-5).map((item) => {
    const event = escapeHtml(item.event || "event");
    const title = escapeHtml(item.alert?.title || item.alert?.type || "alert");
    return `<div class="list-item compact-item"><strong>${event}</strong><div>${title}</div></div>`;
  }).join("");

  container.innerHTML = `
    <div class="alert-history-summary">
      <span>${formatNumber(critical)} active critical</span>
      <span>${formatNumber(raised)} raised / ${formatNumber(cleared)} cleared in ${formatNumber(anomalies?.window_hours || 24)}h</span>
    </div>
    ${latest ? `<details class="alert-history-details"><summary>Recent alert history</summary><div class="stack compact-stack top-space">${latest}</div></details>` : ""}
  `;
}

function renderStatusBanner(snapshot) {
  const banner = byId("status-banner");
  const iconEl = byId("status-banner-icon");
  const textEl = byId("status-banner-text");
  const metaEl = byId("status-banner-meta");
  if (!banner || !textEl) {
    return;
  }

  const fork = snapshot.fork || {};
  const freshness = snapshot.freshness || {};
  const services = snapshot.services || {};
  const sourceHealth = snapshot.source_health || {};
  const alerts = activeAlertList(snapshot.alerts || []);
  const servicesStatus = services.summary?.overall_status || "unknown";
  const rpcStatus = snapshot.rpc_local_status || sourceHealth.rpc_local?.status || "unknown";
  const coreExplorerStatus = sourceHealth.explorer_local?.status || "unknown";
  const snapshotStatus = freshness.snapshot_status || "normal";
  const chainMoving = fork.chain_moving_status || "unknown";
  const lastBlockAge = Number(snapshot.last_block_age ?? freshness.last_block_age_seconds ?? 0);
  const blockTarget = 60;
  const hasHeight = snapshot.height !== null && snapshot.height !== undefined;
  const hasChainSplit = (snapshot.comparison_results || []).some((entry) => entry.match_state === "mismatch");
  const hasCriticalAlert = alerts.some((alert) => alert.severity === "critical" && !["public_site_down", "public_services_down", "mempool_zero"].includes(alert.type));

  const isBad =
    chainMoving === "stalled" ||
    hasChainSplit ||
    hasCriticalAlert ||
    (snapshotStatus === "critical_stale" && !hasHeight) ||
    (rpcStatus === "down" && coreExplorerStatus === "down");

  const isWarn =
    !isBad && (
      !hasHeight ||
      chainMoving === "slow" ||
      rpcStatus === "cooldown" ||
      servicesStatus === "degraded" ||
      servicesStatus === "down" ||
      snapshotStatus === "stale" ||
      lastBlockAge > blockTarget * 3 ||
      alerts.some((alert) => alert.severity === "warning")
    );

  let label;
  if (isBad) {
    label = hasChainSplit ? "Chain split warning" : "Chain issue detected";
  } else if (isWarn) {
    label = "Network running · Some telemetry lag";
  } else {
    label = "Network running";
  }

  const metaParts = [];
  if (hasHeight) {
    metaParts.push(`Height ${formatNumber(snapshot.height)}`);
  }
  if (snapshot.last_block_age !== null && snapshot.last_block_age !== undefined) {
    metaParts.push(`Last block ${formatDuration(snapshot.last_block_age)} ago`);
  }
  metaParts.push(`RPC: ${rpcStatus}`);
  if (servicesStatus && servicesStatus !== "unknown") {
    metaParts.push(`Services: ${servicesStatus}`);
  }

  banner.className = `status-banner status-banner-${isBad ? "bad" : isWarn ? "warn" : "ok"}`;
  iconEl.textContent = isBad ? "❌" : isWarn ? "⚠️" : "✅";
  textEl.textContent = label;
  metaEl.textContent = metaParts.join("  ·  ");
}

function renderFork(fork, snapshot = {}) {
  const currentHeight = fork.current_height ?? snapshot.height;
  const effectiveState = fork.state === "ERROR" && currentHeight ? "POST_FORK" : (fork.state || (currentHeight ? "POST_FORK" : "UNKNOWN"));

  setText("fork-height", fork.fork_height ? formatNumber(fork.fork_height) : "Legacy config not set");
  setText("fork-current-height", formatNumber(currentHeight));
  setText("fork-countdown", formatNumber(fork.remaining_blocks ?? fork.blocks_remaining ?? fork.countdown_blocks));
  setText("fork-upgrade", formatPercent(fork.upgrade_ratio));
  setText("fork-activation", fork.activation_seen ? `YES @ ${fork.activation_height_seen}` : "Not tracked");
  setText("fork-eta", formatDuration(fork.estimated_eta_seconds));
  setText("fork-hoohash-bit", fork.hoohash_bit ? `0x${Number(fork.hoohash_bit).toString(16)}` : "Legacy config not set");
  setText("fork-xelis-bit", fork.xelis_bit ? `0x${Number(fork.xelis_bit).toString(16)}` : "Legacy config not set");
  setText("fork-blocks-after", fork.blocks_after_fork ? formatNumber(fork.blocks_after_fork) : "-");
  setText("fork-last-block-age", formatDuration(fork.last_block_age ?? snapshot.last_block_age));

  const t8m = snapshot.avg_block_time_8m;
  const t30m = snapshot.avg_block_time_30m;
  const t2h = snapshot.avg_block_time_2h;
  const primaryBlockTime = t8m ?? t30m ?? t2h ?? null;
  setText("fork-avg-block-8m", formatFloat(primaryBlockTime, 2, "s"));

  const windowDetail = byId("fork-block-time-windows");
  if (windowDetail) {
    const parts = [];
    if (t30m !== null && t30m !== undefined && t30m !== t8m) {
      parts.push(`30m: ${formatFloat(t30m, 2, "s")}`);
    }
    if (t2h !== null && t2h !== undefined && t2h !== t8m && t2h !== t30m) {
      parts.push(`2h: ${formatFloat(t2h, 2, "s")}`);
    }
    windowDetail.textContent = parts.join("  ·  ");
  }

  const movingBadge = byId("fork-moving-status");
  if (movingBadge) {
    const moving = fork.chain_moving_status || "unknown";
    movingBadge.textContent = moving === "healthy" ? "RUNNING" : moving.toUpperCase();
    movingBadge.className = "status-badge";
    if (moving === "healthy") {
      movingBadge.classList.add("status-postfork");
    } else if (moving === "slow" || moving === "unknown") {
      movingBadge.classList.add("status-activating");
    } else if (moving === "stalled") {
      movingBadge.classList.add("status-error");
    } else {
      movingBadge.classList.add("status-prefork");
    }
  }

  const badge = byId("fork-state");
  if (badge) {
    badge.textContent = effectiveState === "POST_FORK" ? "Live / post-upgrade" : effectiveState;
    badge.className = "status-badge";
    if (effectiveState === "POST_FORK") {
      badge.classList.add("status-postfork");
    } else if (effectiveState === "PRE_FORK") {
      badge.classList.add("status-prefork");
    } else if (effectiveState === "ACTIVATING") {
      badge.classList.add("status-activating");
    } else {
      badge.classList.add("status-activating");
    }
  }

  const readiness = byId("fork-readiness");
  if (readiness) {
    readiness.textContent = fork.readiness_level || "normal";
    readiness.className = "status-badge";
    readiness.classList.add(statusBadgeClass(fork.readiness_level));
  }

  const stall = byId("fork-stall");
  if (stall) {
    stall.textContent = fork.stall_level || "normal";
    stall.className = "status-badge";
    stall.classList.add(statusBadgeClass(fork.stall_level));
  }

  const reasons = byId("fork-reasons");
  if (reasons) {
    reasons.innerHTML = "";
    const readinessReasons = fork.readiness_reasons || ["Legacy fork settings are no longer required for normal live monitoring."];
    readinessReasons.forEach((reason) => {
      const item = document.createElement("li");
      item.className = "list-item";
      item.textContent = reason;
      reasons.appendChild(item);
    });
  }
}
