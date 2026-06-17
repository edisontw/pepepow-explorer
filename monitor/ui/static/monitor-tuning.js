// Calmer public monitor presentation overrides. Loaded after monitor.js.

let cachedPepepowPriceUsdt = null;
let priceFetchInFlight = false;
let latestRewardSnapshot = null;

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

function estimateHashrateDisplay(snapshot) {
  if (snapshot.hashrate_display && snapshot.hashrate_display !== "-") {
    return snapshot.hashrate_display;
  }
  const difficulty = Number(snapshot.difficulty);
  const blockTime = Number(snapshot.avg_block_time_8m || snapshot.avg_block_time_30m || snapshot.avg_block_time_2h || 0);
  if (!Number.isFinite(difficulty) || difficulty <= 0 || !Number.isFinite(blockTime) || blockTime <= 0) {
    return "-";
  }
  return formatHashrateValue((difficulty * 4294967296) / blockTime);
}

function formatHashrateValue(value) {
  const units = ["H/s", "KH/s", "MH/s", "GH/s", "TH/s", "PH/s"];
  let amount = Math.max(0, Number(value) || 0);
  let index = 0;
  while (amount >= 1000 && index < units.length - 1) {
    amount /= 1000;
    index += 1;
  }
  return `${amount.toFixed(4)} ${units[index]}`;
}

function compatibleEnabledDisplay(snapshot) {
  const enabled = Number(snapshot.masternode_enabled || 0);
  const upgraded = Number(snapshot.masternode_upgraded_enabled || 0);
  const legacy = Number(snapshot.masternode_legacy_enabled || 0);
  const unknown = Number(snapshot.masternode_unknown_enabled || 0);
  if (upgraded > 0) {
    return formatNumber(upgraded);
  }
  if (enabled > 0 && legacy === 0 && unknown >= enabled) {
    return `${formatNumber(enabled)} checking`;
  }
  return formatNumber(upgraded);
}

function renderMasternodes(snapshot) {
  setText("mn-enabled", formatNumber(snapshot.masternode_enabled));
  setText("mn-total", formatNumber(snapshot.masternode_total));
  setText("mn-upgraded", compatibleEnabledDisplay(snapshot));
  setText("mn-legacy", formatNumber(snapshot.masternode_legacy_enabled));
  setText("mn-upgrade-ratio", snapshot.masternode_upgraded_enabled > 0 ? formatPercent(snapshot.upgrade_ratio) : "Checking");

  const compatDiv = byId("mn-compatibility-summary");
  if (compatDiv) {
    compatDiv.innerHTML = "";
    const alertDiv = document.createElement("div");
    if (snapshot.masternode_legacy_enabled > 0) {
      alertDiv.className = "alert-item warning";
      alertDiv.innerHTML = "<strong>Some enabled masternodes may still be running legacy versions.</strong><div>They may not follow the post-upgrade network correctly.</div>";
    } else if (snapshot.masternode_upgraded_enabled > 0) {
      alertDiv.className = "alert-item info";
      alertDiv.innerHTML = "<strong>Enabled masternodes appear compatible with the post-upgrade network.</strong>";
    } else {
      alertDiv.className = "alert-item info";
      alertDiv.innerHTML = "<strong>Masternode version classification is still checking.</strong><div>Enabled count is available, but version mapping is incomplete.</div>";
    }
    compatDiv.appendChild(alertDiv);
  }

  const body = byId("mn-version-breakdown");
  body.innerHTML = "";
  const versions = normalizeMasternodeVersions(snapshot.masternode_versions);
  if (!versions.length) {
    const row = document.createElement("tr");
    row.innerHTML = "<td colspan='3'>No masternode version data</td>";
    body.appendChild(row);
    return;
  }
  versions.forEach((entry) => {
    const row = document.createElement("tr");
    const tagClass = entry.is_upgraded === true ? "latest" : entry.is_upgraded === false ? "legacy" : "unknown";
    const tagLabel = entry.is_upgraded === true ? "Latest" : entry.is_upgraded === false ? "Legacy" : "Checking";
    row.innerHTML = `
      <td>
        <span class="version-chip">
          <span>${entry.protocol_version ?? "unknown"}</span>
          <span class="version-tag ${tagClass}">${tagLabel}</span>
        </span>
      </td>
      <td>${entry.semver || "-"}</td>
      <td>${formatNumber(entry.count)}</td>
    `;
    body.appendChild(row);
  });
}

function renderPeerSummary(peers) {
  const summary = peers.summary || {};
  const items = peers.items || [];
  const total = Number(summary.total_peers || summary.total || window.latestPeerCount || items.length || 0);
  const upgraded = Number(summary.upgraded_peers || 0);
  const legacy = Number(summary.legacy_peers || 0);
  const unknown = Math.max(0, Number(summary.unknown_peers ?? (total - upgraded - legacy)) || 0);
  const peerSummary = byId("peer-summary");
  if (peerSummary) {
    peerSummary.innerHTML = `
      <div class="metric-grid">
        <div class="metric"><span class="label">Total peers</span><strong>${formatNumber(total)}</strong></div>
        <div class="metric"><span class="label">Upgraded</span><strong>${formatNumber(upgraded)}</strong></div>
        <div class="metric"><span class="label">Legacy</span><strong>${formatNumber(legacy)}</strong></div>
        <div class="metric"><span class="label">Unknown</span><strong>${formatNumber(unknown)}</strong></div>
      </div>
    `;
  }

  const list = byId("peer-versions");
  if (!list) {
    return;
  }
  list.innerHTML = "";
  const versions = summary.versions || [];
  if (!versions.length && items.length) {
    const item = document.createElement("li");
    item.className = "list-item";
    item.textContent = `${items.length} peer records available; version summary is still checking.`;
    list.appendChild(item);
    return;
  }
  versions.forEach((entry) => {
    const item = document.createElement("li");
    item.className = "list-item";
    item.textContent = `${entry.label}: ${entry.count}`;
    list.appendChild(item);
  });
}

function extractPriceValue(payload) {
  if (payload === null || payload === undefined) {
    return null;
  }
  if (typeof payload === "number") {
    return payload;
  }
  if (typeof payload === "string") {
    const value = Number(payload.replace(/[^0-9.eE-]/g, ""));
    return Number.isFinite(value) ? value : null;
  }
  const keys = ["price", "last", "usd", "usdt", "price_usd", "price_usdt", "current_price"];
  for (const key of keys) {
    if (payload[key] !== undefined) {
      const value = extractPriceValue(payload[key]);
      if (value !== null) {
        return value;
      }
    }
  }
  for (const value of Object.values(payload)) {
    if (typeof value === "object" && value !== null) {
      const nested = extractPriceValue(value);
      if (nested !== null) {
        return nested;
      }
    }
  }
  return null;
}

async function fetchPepepowPrice() {
  if (cachedPepepowPriceUsdt !== null || priceFetchInFlight) {
    return;
  }
  priceFetchInFlight = true;
  try {
    const response = await fetch(`${window.location.origin}/ext/getcurrentprice`, { headers: { Accept: "application/json" } });
    if (!response.ok) {
      throw new Error(`price request failed: ${response.status}`);
    }
    const text = await response.text();
    let payload;
    try {
      payload = JSON.parse(text);
    } catch (_) {
      payload = text;
    }
    cachedPepepowPriceUsdt = extractPriceValue(payload);
    renderMonthlyReward(latestRewardSnapshot);
  } catch (error) {
    console.warn("price fetch failed", error);
  } finally {
    priceFetchInFlight = false;
  }
}

function renderMonthlyReward(snapshot) {
  if (!snapshot) {
    return;
  }
  const target = byId("reward-month-usdt");
  if (!target) {
    return;
  }
  const perDay = Number(snapshot.reward_estimate?.per_day || 0);
  if (!perDay) {
    target.textContent = "-";
    return;
  }
  if (cachedPepepowPriceUsdt === null) {
    target.textContent = "Loading price…";
    return;
  }
  const monthlyCoin = perDay * 30;
  const monthlyUsdt = monthlyCoin * cachedPepepowPriceUsdt;
  target.textContent = `${monthlyUsdt.toLocaleString(undefined, { maximumFractionDigits: 2 })} USDT`;
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

const baseRenderSnapshot = renderSnapshot;
renderSnapshot = function tunedRenderSnapshot(snapshot) {
  window.latestPeerCount = Number(snapshot.peer_count || 0);
  if ((!snapshot.hashrate_display || snapshot.hashrate_display === "-") && snapshot.difficulty) {
    snapshot = { ...snapshot, hashrate_display: estimateHashrateDisplay(snapshot) };
  }
  baseRenderSnapshot(snapshot);
  setText("network-hashrate", estimateHashrateDisplay(snapshot));
  latestRewardSnapshot = snapshot;
  renderMonthlyReward(snapshot);
  fetchPepepowPrice();
};
