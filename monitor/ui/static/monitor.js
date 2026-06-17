const rootPath = document.body.dataset.rootPath || "";
const statusUrl = `${rootPath}/api/status`;
const masternodesUrl = `${rootPath}/api/masternodes`;
const myNodesStorageKey = "myNodes";
const statusPollIntervalMs = 10000;
const masternodesPollIntervalMs = 30000;

let hashrateChart;
let intervalChart;
let myNodesInitialized = false;
let latestSnapshotTargetVersion = "2.9.0.2";
let latestMasternodesPayload = { items: [], list_generated_at: null, stale: true };
let cachedMasternodeLookup;
let cachedMasternodeLookupKey = "";
let lastChartKeys = { hashrate: "", interval: "" };
let lastSectionKeys = {
  services: "",
  pools: "",
  alerts: "",
  anomalies: "",
  peers: "",
  masternodes: "",
  blocks: "",
  comparison: "",
};

function byId(id) {
  return document.getElementById(id);
}

function formatNumber(value) {
  if (value === null || value === undefined || value === "") {
    return "-";
  }
  return new Intl.NumberFormat().format(value);
}

function formatFloat(value, digits = 2, suffix = "") {
  if (value === null || value === undefined || value === "") {
    return "-";
  }
  return `${Number(value).toFixed(digits)}${suffix}`;
}

function formatLatencyMs(value) {
  if (value === null || value === undefined || value === "") {
    return "-";
  }
  return `${Number(value).toFixed(2)} ms`;
}

function formatPercent(value) {
  if (value === null || value === undefined) {
    return "-";
  }
  return `${(Number(value) * 100).toFixed(2)}%`;
}

function formatDuration(seconds) {
  if (seconds === null || seconds === undefined) {
    return "-";
  }
  const total = Math.max(0, Number(seconds));
  if (total < 60) {
    return `${Math.round(total)}s`;
  }
  if (total < 3600) {
    return `${Math.floor(total / 60)}m ${Math.round(total % 60)}s`;
  }
  return `${Math.floor(total / 3600)}h ${Math.floor((total % 3600) / 60)}m`;
}

function formatAbsoluteUtc(value) {
  if (!value) {
    return "Waiting for first snapshot";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  const year = date.getUTCFullYear();
  const month = String(date.getUTCMonth() + 1).padStart(2, "0");
  const day = String(date.getUTCDate()).padStart(2, "0");
  const hours = String(date.getUTCHours()).padStart(2, "0");
  const minutes = String(date.getUTCMinutes()).padStart(2, "0");
  const seconds = String(date.getUTCSeconds()).padStart(2, "0");
  return `${year}-${month}-${day} ${hours}:${minutes}:${seconds} UTC`;
}

function formatRelativeTime(value) {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "-";
  }
  const diffSeconds = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000));
  return `${formatDuration(diffSeconds)} ago`;
}

function formatUnixRelativeTime(value) {
  if (value === null || value === undefined) {
    return "-";
  }
  const diffSeconds = Math.max(0, Math.floor(Date.now() / 1000) - Number(value));
  return `${formatDuration(diffSeconds)} ago`;
}

function shortHash(hash) {
  if (!hash) {
    return "-";
  }
  return `${hash.slice(0, 10)}...${hash.slice(-8)}`;
}

function setText(id, value) {
  const element = byId(id);
  if (element) {
    element.textContent = value;
  }
}

function renderAlerts(alerts) {
  const list = byId("alerts-list");
  list.innerHTML = "";
  if (!alerts.length) {
    const item = document.createElement("li");
    item.className = "alert-item info";
    item.textContent = "No active alerts.";
    list.appendChild(item);
    return;
  }

  alerts.forEach((alert) => {
    const item = document.createElement("li");
    item.className = `alert-item ${alert.severity}`;
    item.innerHTML = `<strong>${alert.title}</strong><div>${alert.message}</div>`;
    list.appendChild(item);
  });
}

function statusBadgeClass(value) {
  if (value === "critical" || value === "down" || value === "stale" || value === "critical_stale" || value === "ERROR") {
    return "status-error";
  }
  if (value === "warning" || value === "degraded" || value === "ACTIVATING") {
    return "status-activating";
  }
  if (value === "ok" || value === "fresh" || value === "complete" || value === "POST_FORK") {
    return "status-postfork";
  }
  return "status-prefork";
}

function freshnessRowClass(value) {
  if (value === "critical_stale") {
    return "freshness-critical";
  }
  if (value === "stale") {
    return "freshness-stale";
  }
  return "freshness-normal";
}

function buildSignature(value) {
  return JSON.stringify(value ?? null);
}

function summarizeFreshnessDiagnosis(freshness) {
  if (freshness.snapshot_status && freshness.snapshot_status !== "normal") {
    return "Monitor snapshot is stale. Current chain state may be outdated.";
  }
  if (freshness.last_block_status && freshness.last_block_status !== "normal") {
    return "Snapshot is fresh, but block production looks slow or stalled.";
  }
  if (freshness.mn_cache_status && freshness.mn_cache_status !== "normal") {
    return "Chain data is fresh. Masternode cache is lagging behind.";
  }
  if (freshness.site_status_status && freshness.site_status_status !== "normal") {
    return "Chain data is fresh. Public site checks are older than expected.";
  }
  if (freshness.daemon_status && freshness.daemon_status !== "normal") {
    return "Daemon-backed data is aging faster than expected.";
  }
  if (freshness.explorer_status && freshness.explorer_status !== "normal") {
    return "Explorer-backed data is aging faster than expected.";
  }
  return "Snapshot, chain, masternode cache, and site checks all look fresh.";
}

function renderFreshnessSummary(freshness) {
  const container = byId("freshness-summary");
  if (!container) {
    return;
  }
  const rows = [
    { label: "Snapshot age", value: formatDuration(freshness.snapshot_age_seconds), status: freshness.snapshot_status },
    { label: "Last block age", value: formatDuration(freshness.last_block_age_seconds), status: freshness.last_block_status },
    { label: "MN cache age", value: formatDuration(freshness.mn_cache_age_seconds ?? freshness.masternode_list_age_seconds), status: freshness.mn_cache_status },
    { label: "Site check age", value: formatDuration(freshness.site_status_age_seconds ?? freshness.site_checks_age_seconds), status: freshness.site_status_status },
  ];

  if (freshness.daemon_data_age_seconds !== null && freshness.daemon_data_age_seconds !== undefined) {
    rows.push({ label: "Daemon data age", value: formatDuration(freshness.daemon_data_age_seconds), status: freshness.daemon_status });
  }
  if (freshness.explorer_data_age_seconds !== null && freshness.explorer_data_age_seconds !== undefined) {
    rows.push({ label: "Explorer data age", value: formatDuration(freshness.explorer_data_age_seconds), status: freshness.explorer_status });
  }

  container.innerHTML = `
    <div class="freshness-grid">
      ${rows.map((row) => `
        <div class="list-item freshness-row ${freshnessRowClass(row.status)}">
          <span class="label">${row.label}</span>
          <strong>${row.value}</strong>
          <span class="version-tag freshness-tag ${row.status === "critical_stale" ? "legacy" : row.status === "stale" ? "unknown" : "latest"}">${row.status || "normal"}</span>
        </div>
      `).join("")}
    </div>
    <div class="list-item freshness-diagnosis ${freshnessRowClass(freshness.overall_status)}">
      <strong>${freshness.overall_status || "normal"}</strong>
      <div>${summarizeFreshnessDiagnosis(freshness)}</div>
    </div>
  `;
}

function renderAnomalySummary(anomalies) {
  const container = byId("anomaly-summary");
  if (!container) {
    return;
  }
  const latest = (anomalies.latest || []).map((item) => {
    const event = item.event || "event";
    const title = item.alert?.title || item.alert?.type || "alert";
    return `<div class="list-item compact-item"><strong>${escapeHtml(event)}</strong><div>${escapeHtml(title)}</div></div>`;
  }).join("");
  container.innerHTML = `
    <div class="metric-grid summary-grid">
      <div class="metric"><span class="label">Raised (24h)</span><strong>${formatNumber(anomalies.raised_count || 0)}</strong></div>
      <div class="metric"><span class="label">Cleared (24h)</span><strong>${formatNumber(anomalies.cleared_count || 0)}</strong></div>
      <div class="metric"><span class="label">Active critical</span><strong>${formatNumber(anomalies.active_critical_count || 0)}</strong></div>
      <div class="metric"><span class="label">Window</span><strong>${formatNumber(anomalies.window_hours || 24)}h</strong></div>
    </div>
    ${latest ? `<div class="stack compact-stack top-space">${latest}</div>` : ""}
  `;
}

function renderPeerSummary(peers) {
  const summary = peers.summary || {};
  byId("peer-summary").innerHTML = `
    <div class="metric-grid">
      <div class="metric"><span class="label">Total peers</span><strong>${formatNumber(summary.total_peers || 0)}</strong></div>
      <div class="metric"><span class="label">Upgraded</span><strong>${formatNumber(summary.upgraded_peers || 0)}</strong></div>
      <div class="metric"><span class="label">Legacy</span><strong>${formatNumber(summary.legacy_peers || 0)}</strong></div>
      <div class="metric"><span class="label">Unknown</span><strong>${formatNumber(summary.unknown_peers || 0)}</strong></div>
    </div>
  `;

  const list = byId("peer-versions");
  list.innerHTML = "";
  (summary.versions || []).forEach((entry) => {
    const item = document.createElement("li");
    item.className = "list-item";
    item.textContent = `${entry.label}: ${entry.count}`;
    list.appendChild(item);
  });
}

function renderMasternodes(snapshot) {
  setText("mn-enabled", formatNumber(snapshot.masternode_enabled));
  setText("mn-total", formatNumber(snapshot.masternode_total));
  setText("mn-upgraded", formatNumber(snapshot.masternode_upgraded_enabled));
  setText("mn-legacy", formatNumber(snapshot.masternode_legacy_enabled));
  setText("mn-upgrade-ratio", formatPercent(snapshot.upgrade_ratio));

  const compatDiv = byId("mn-compatibility-summary");
  if (compatDiv) {
    compatDiv.innerHTML = "";
    const alertDiv = document.createElement("div");
    if (snapshot.masternode_legacy_enabled > 0) {
      alertDiv.className = "alert-item warning";
      alertDiv.innerHTML = "<strong>Some enabled masternodes may still be running legacy versions.</strong><div>They may not follow the post-fork network correctly.</div>";
    } else {
      alertDiv.className = "alert-item info";
      alertDiv.innerHTML = "<strong>Most enabled masternodes appear compatible with the post-fork network.</strong>";
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
    const tagLabel = entry.is_upgraded === true ? "Latest" : entry.is_upgraded === false ? "Legacy" : "Unmapped";
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

function normalizeMasternodeVersions(payload) {
  if (Array.isArray(payload)) {
    return payload
      .filter((entry) => entry && typeof entry === "object" && !Array.isArray(entry))
      .map((entry) => ({
        protocol_version: Number.isFinite(Number(entry.protocol_version)) ? Number(entry.protocol_version) : null,
        semver: typeof entry.semver === "string" && entry.semver.trim() ? entry.semver.trim() : null,
        count: Number.isFinite(Number(entry.count)) ? Number(entry.count) : null,
        is_upgraded: entry.is_upgraded === true ? true : entry.is_upgraded === false ? false : null,
      }))
      .filter((entry) => entry.count !== null && entry.count > 0 && (entry.protocol_version !== null || entry.semver !== null));
  }

  if (payload && typeof payload === "object") {
    return Object.entries(payload)
      .map(([key, value]) => {
        const protocol = Number(key);
        const count = Number(value);
        return {
          protocol_version: Number.isFinite(protocol) ? protocol : null,
          semver: null,
          count: Number.isFinite(count) ? count : null,
          is_upgraded: null,
        };
      })
      .filter((entry) => entry.count !== null && entry.count > 0);
  }

  return [];
}

function renderSourceHealth(sourceHealth, snapshot) {
  const list = byId("source-health");
  list.innerHTML = "";
  ["rpc_local", "explorer_local", "public_api_remote"].forEach((name) => {
    const entry = sourceHealth[name] || { name, status: "unknown" };
    const item = document.createElement("li");
    item.className = "list-item";
    const cooldown = name === "rpc_local" ? ` | Cooldown: ${formatDuration(snapshot.cooldown_remaining_seconds || 0)}` : "";
    item.innerHTML = `<strong>${entry.name}</strong> <span>${entry.status}</span><div>Latency: ${entry.latency_ms ?? "-"} ms${cooldown}</div>`;
    list.appendChild(item);
  });
}

function renderServicesSummary(services) {
  const container = byId("services-summary");
  const summary = services.summary || {};
  container.innerHTML = `
    <div class="metric-grid summary-grid">
      <div class="metric"><span class="label">Overall</span><strong>${summary.overall_status || "-"}</strong></div>
      <div class="metric"><span class="label">OK</span><strong>${formatNumber(summary.ok_count || 0)}</strong></div>
      <div class="metric"><span class="label">Degraded</span><strong>${formatNumber(summary.degraded_count || 0)}</strong></div>
      <div class="metric"><span class="label">Down</span><strong>${formatNumber(summary.down_count || 0)}</strong></div>
    </div>
  `;

  const body = byId("public-sites");
  body.innerHTML = "";
  (services.public_sites || []).forEach((site) => {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>${escapeHtml(site.name || site.url || "-")}</td>
      <td><span class="version-tag ${site.status === "ok" ? "latest" : site.status === "down" ? "legacy" : "unknown"}">${escapeHtml(site.status || "unknown")}</span></td>
      <td>${site.status_code ?? "-"}</td>
      <td>${formatLatencyMs(site.latency_ms)}</td>
      <td>${site.last_checked_at ? `${formatRelativeTime(site.last_checked_at)} (${formatAbsoluteUtc(site.last_checked_at)})` : "-"}</td>
    `;
    body.appendChild(row);
  });

  if (!(services.public_sites || []).length) {
    const row = document.createElement("tr");
    row.innerHTML = "<td colspan='5' class='empty-state'>No public site checks yet</td>";
    body.appendChild(row);
  }
}

function miningPoolTagClass(status) {
  if (status === "up") {
    return "latest";
  }
  if (status === "down") {
    return "legacy";
  }
  return "unknown";
}

function renderMiningPools(services) {
  const container = byId("mining-pool-summary");
  const body = byId("mining-pools");
  const summary = services.mining_pool_summary || {};
  const pools = services.mining_pools || [];
  container.innerHTML = `
    <div class="metric-grid summary-grid">
      <div class="metric"><span class="label">Reachable pools</span><strong>${formatNumber(summary.reachable_pools || 0)}</strong></div>
      <div class="metric"><span class="label">Healthy stratum pools</span><strong>${formatNumber(summary.healthy_stratum_pools || 0)}</strong></div>
    </div>
  `;

  body.innerHTML = "";
  pools.forEach((pool) => {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>${escapeHtml(pool.endpoint || `${pool.host || "-"}:${pool.port ?? "-"}`)}</td>
      <td><span class="version-tag ${miningPoolTagClass(pool.status)}">${escapeHtml(pool.status || "unknown")}</span></td>
      <td>${formatLatencyMs(pool.latency_ms)}</td>
      <td>${pool.last_ok_at ? `${formatRelativeTime(pool.last_ok_at)} (${formatAbsoluteUtc(pool.last_ok_at)})` : "-"}</td>
      <td>${pool.checked_at ? `${formatRelativeTime(pool.checked_at)} (${formatAbsoluteUtc(pool.checked_at)})` : "-"}</td>
      <td>${escapeHtml(pool.error || "-")}</td>
    `;
    body.appendChild(row);
  });

  if (!pools.length) {
    const row = document.createElement("tr");
    row.innerHTML = "<td colspan='6' class='empty-state'>No mining pool checks yet</td>";
    body.appendChild(row);
  }
}

function renderRecentBlocks(blocks) {
  const body = byId("recent-blocks");
  body.innerHTML = "";
  blocks.slice().reverse().slice(0, 18).forEach((block) => {
    const row = document.createElement("tr");
    const isPostFork = block.height >= 4354200;
    const algoLabel = isPostFork ? "Hoohash / post-fork" : "pre-fork / legacy";
    const algoClass = isPostFork ? "latest" : "legacy";

    row.innerHTML = `
      <td>${formatNumber(block.height)}</td>
      <td>${shortHash(block.hash)}</td>
      <td>${block.version_hex}</td>
      <td><span class="version-tag ${algoClass}">${algoLabel}</span></td>
      <td>${block.interval_from_prev ?? "-"}</td>
      <td>${block.difficulty ?? "-"}</td>
      <td>${formatUnixRelativeTime(block.time)}</td>
      <td>${escapeHtml(block.source || "-")}</td>
    `;
    body.appendChild(row);
  });
}

function renderComparison(results) {
  const list = byId("comparison-results");
  list.innerHTML = "";
  const summaryDiv = byId("comparison-summary");
  if (summaryDiv) {
    summaryDiv.innerHTML = "";
  }

  if (!results.length) {
    const item = document.createElement("li");
    item.className = "list-item";
    item.textContent = "No comparison nodes configured.";
    list.appendChild(item);
    return;
  }

  let hasHashMismatch = false;
  let hasLargeHeightDivergence = false;

  results.forEach((entry) => {
    const item = document.createElement("li");
    item.className = "list-item";
    item.innerHTML = `<strong>${entry.name}</strong> <span>${entry.match_state}</span><div>Remote height: ${entry.remote_height ?? "-"} | Remote hash: ${shortHash(entry.remote_hash)}</div>`;
    list.appendChild(item);

    if (entry.match_state === "mismatch") {
      hasHashMismatch = true;
    }
    if (entry.remote_height !== null && entry.local_height !== null) {
      if (Math.abs(entry.remote_height - entry.local_height) >= 5) {
        hasLargeHeightDivergence = true;
      }
    }
  });

  if (summaryDiv) {
    const alertDiv = document.createElement("div");
    if (hasHashMismatch) {
      alertDiv.className = "alert-item critical";
      alertDiv.innerHTML = "<strong>Possible fork / chain split detected</strong>";
    } else if (hasLargeHeightDivergence) {
      alertDiv.className = "alert-item critical";
      alertDiv.innerHTML = "<strong>Height divergence detected</strong>";
    } else {
      alertDiv.className = "alert-item info";
      alertDiv.innerHTML = "<strong>Comparison nodes aligned</strong>";
    }
    summaryDiv.appendChild(alertDiv);
  }
}

function ensureCharts() {
  if (hashrateChart && intervalChart) {
    return;
  }

  hashrateChart = new Chart(byId("hashrate-chart"), {
    type: "line",
    data: { labels: [], datasets: [{ label: "H/s", data: [], borderColor: "#4ee4b1", tension: 0.2 }] },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } },
  });

  intervalChart = new Chart(byId("interval-chart"), {
    type: "line",
    data: { labels: [], datasets: [{ label: "Seconds", data: [], borderColor: "#ffd166", tension: 0.2 }] },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } },
  });
}

function renderCharts(snapshot) {
  ensureCharts();
  const hashrateKey = buildSignature(snapshot.recent_hashrate || []);
  if (hashrateKey !== lastChartKeys.hashrate) {
    hashrateChart.data.labels = (snapshot.recent_hashrate || []).map((point) => point.height);
    hashrateChart.data.datasets[0].data = (snapshot.recent_hashrate || []).map((point) => point.value);
    hashrateChart.update();
    lastChartKeys.hashrate = hashrateKey;
  }

  const intervalKey = buildSignature(snapshot.recent_block_intervals || []);
  if (intervalKey !== lastChartKeys.interval) {
    intervalChart.data.labels = (snapshot.recent_block_intervals || []).map((point) => point.height);
    intervalChart.data.datasets[0].data = (snapshot.recent_block_intervals || []).map((point) => point.value);
    intervalChart.update();
    lastChartKeys.interval = intervalKey;
  }
}

function renderFork(fork, snapshot = {}) {
  setText("fork-height", formatNumber(fork.fork_height));
  setText("fork-current-height", formatNumber(fork.current_height));
  setText("fork-countdown", formatNumber(fork.remaining_blocks ?? fork.blocks_remaining ?? fork.countdown_blocks));
  setText("fork-upgrade", formatPercent(fork.upgrade_ratio));
  setText("fork-activation", fork.activation_seen ? `YES @ ${fork.activation_height_seen}` : "NO");
  setText("fork-eta", formatDuration(fork.estimated_eta_seconds));
  setText("fork-hoohash-bit", fork.hoohash_bit ? `0x${Number(fork.hoohash_bit).toString(16)}` : "-");
  setText("fork-xelis-bit", fork.xelis_bit ? `0x${Number(fork.xelis_bit).toString(16)}` : "-");

  // New post-fork indicators:
  setText("fork-blocks-after", formatNumber(fork.blocks_after_fork));
  setText("fork-last-block-age", formatDuration(fork.last_block_age));
  setText("fork-avg-block-8m", formatFloat(snapshot.avg_block_time_8m, 2, "s"));
  setText("fork-avg-block-30m", formatFloat(snapshot.avg_block_time_30m, 2, "s"));
  setText("fork-avg-block-2h", formatFloat(snapshot.avg_block_time_2h, 2, "s"));

  const movingBadge = byId("fork-moving-status");
  if (movingBadge) {
    movingBadge.textContent = (fork.chain_moving_status || "unknown").toUpperCase();
    movingBadge.className = "status-badge";
    if (fork.chain_moving_status === "healthy") {
      movingBadge.classList.add("status-postfork");
    } else if (fork.chain_moving_status === "slow") {
      movingBadge.classList.add("status-activating");
    } else if (fork.chain_moving_status === "stalled") {
      movingBadge.classList.add("status-error");
    } else {
      movingBadge.classList.add("status-prefork");
    }
  }

  const badge = byId("fork-state");
  badge.textContent = fork.state || "ERROR";
  badge.className = "status-badge";
  if (fork.state === "PRE_FORK") {
    badge.classList.add("status-prefork");
  } else if (fork.state === "ACTIVATING") {
    badge.classList.add("status-activating");
  } else if (fork.state === "POST_FORK") {
    badge.classList.add("status-postfork");
  } else {
    badge.classList.add("status-error");
  }

  const readiness = byId("fork-readiness");
  readiness.textContent = fork.readiness_level || "normal";
  readiness.className = "status-badge";
  readiness.classList.add(statusBadgeClass(fork.readiness_level));

  const stall = byId("fork-stall");
  stall.textContent = fork.stall_level || "normal";
  stall.className = "status-badge";
  stall.classList.add(statusBadgeClass(fork.stall_level));

  const reasons = byId("fork-reasons");
  reasons.innerHTML = "";
  const readinessReasons = fork.readiness_reasons || [];
  if (!readinessReasons.length) {
    const item = document.createElement("li");
    item.className = "list-item";
    item.textContent = "No extra readiness warnings.";
    reasons.appendChild(item);
  } else {
    readinessReasons.forEach((reason) => {
      const item = document.createElement("li");
      item.className = "list-item";
      item.textContent = reason;
      reasons.appendChild(item);
    });
  }
}

function summarizeServices(services) {
  const overall = services.summary?.overall_status || "unknown";
  if (overall === "ok") {
    return "all ok";
  }
  return overall;
}

function renderSnapshot(snapshot) {
  latestSnapshotTargetVersion = snapshot.target_version || "2.9.0.2";
  setText("generated-at", formatAbsoluteUtc(snapshot.generated_at));
  setText("generated-at-relative", formatRelativeTime(snapshot.generated_at));
  setText("network-height", formatNumber(snapshot.height));
  setText("network-avg-block-8m", formatFloat(snapshot.avg_block_time_8m ?? snapshot.avg_block_time_5m ?? snapshot.avg_block_time_3m, 2, "s"));
  setText("network-last-block-age", formatDuration(snapshot.last_block_age));
  setText("network-freshness", snapshot.freshness?.overall_status || snapshot.freshness?.status || "-");
  setText("network-difficulty", snapshot.difficulty ?? "-");
  setText("network-hashrate", snapshot.hashrate_display || "-");
  setText("network-upgrade-summary", `${formatPercent(snapshot.upgrade_summary?.ratio)} upgraded`);
  setText("network-services-status", summarizeServices(snapshot.services || {}));
  setText("network-mempool-size", formatNumber(snapshot.mempool_txs));
  const rpcStatus = snapshot.rpc_local_status === "cooldown"
    ? `cooldown (${formatDuration(snapshot.cooldown_remaining_seconds)})`
    : snapshot.rpc_local_status || "-";
  setText("network-rpc-status", rpcStatus);

  renderFreshnessSummary(snapshot.freshness || {});
  renderFork(snapshot.fork || {}, snapshot);
  const masternodesKey = buildSignature([
    snapshot.masternode_enabled,
    snapshot.masternode_total,
    snapshot.masternode_upgraded_enabled,
    snapshot.masternode_legacy_enabled,
    snapshot.masternode_unknown_enabled,
    snapshot.upgrade_ratio,
    snapshot.masternode_versions || [],
  ]);
  if (masternodesKey !== lastSectionKeys.masternodes) {
    renderMasternodes(snapshot);
    lastSectionKeys.masternodes = masternodesKey;
  }

  const alertsKey = buildSignature(snapshot.alerts || []);
  if (alertsKey !== lastSectionKeys.alerts) {
    renderAlerts(snapshot.alerts || []);
    lastSectionKeys.alerts = alertsKey;
  }

  const anomaliesKey = buildSignature(snapshot.recent_anomalies || {});
  if (anomaliesKey !== lastSectionKeys.anomalies) {
    renderAnomalySummary(snapshot.recent_anomalies || {});
    lastSectionKeys.anomalies = anomaliesKey;
  }

  const peersKey = buildSignature(snapshot.peers?.summary || {});
  if (peersKey !== lastSectionKeys.peers) {
    renderPeerSummary(snapshot.peers || {});
    lastSectionKeys.peers = peersKey;
  }

  const servicesKey = buildSignature({
    summary: snapshot.services?.summary || {},
    public_sites: snapshot.services?.public_sites || [],
    source_health: snapshot.source_health || {},
  });
  if (servicesKey !== lastSectionKeys.services) {
    renderServicesSummary(snapshot.services || {});
    renderSourceHealth(snapshot.source_health || {}, snapshot);
    lastSectionKeys.services = servicesKey;
  }

  const poolsKey = buildSignature({
    summary: snapshot.services?.mining_pool_summary || {},
    pools: snapshot.services?.mining_pools || [],
  });
  if (poolsKey !== lastSectionKeys.pools) {
    renderMiningPools(snapshot.services || {});
    lastSectionKeys.pools = poolsKey;
  }

  const blocksKey = buildSignature(snapshot.recent_blocks || []);
  if (blocksKey !== lastSectionKeys.blocks) {
    renderRecentBlocks(snapshot.recent_blocks || []);
    lastSectionKeys.blocks = blocksKey;
  }

  const comparisonKey = buildSignature(snapshot.comparison_results || []);
  if (comparisonKey !== lastSectionKeys.comparison) {
    renderComparison(snapshot.comparison_results || []);
    lastSectionKeys.comparison = comparisonKey;
  }

  const reward = snapshot.reward_estimate;
  if (reward && reward.block_reward !== null) {
    byId("reward-configured-container").classList.remove("hidden");
    byId("reward-unconfigured-container").classList.add("hidden");
    if (reward.per_20s !== null) {
      setText("reward-20s", formatFloat(reward.per_20s, 6, " PEPEW"));
      setText("reward-hour", formatFloat(reward.per_hour, 6, " PEPEW"));
      setText("reward-day", formatFloat(reward.per_day, 6, " PEPEW"));
      setText("reward-block-reward", formatFloat(reward.block_reward, 2, " PEPEW"));
    } else {
      setText("reward-20s", "N/A");
      setText("reward-hour", "N/A");
      setText("reward-day", "N/A");
      setText("reward-block-reward", formatFloat(reward.block_reward, 2, " PEPEW"));
    }
  } else {
    byId("reward-configured-container").classList.add("hidden");
    byId("reward-unconfigured-container").classList.remove("hidden");
  }

  renderCharts(snapshot);

  byId("stale-indicator").classList.toggle("hidden", !snapshot.stale);
}

function loadMyNodes() {
  try {
    const payload = JSON.parse(window.localStorage.getItem(myNodesStorageKey) || "[]");
    if (!Array.isArray(payload)) {
      return [];
    }
    return payload
      .filter((item) => item && typeof item === "object")
      .map((item) => ({
        key: typeof item.key === "string" ? item.key.trim() : "",
        type: item.type === "txid" || item.type === "ip" ? item.type : "address",
        label: typeof item.label === "string" && item.label.trim() ? item.label.trim() : "My Node",
        addedAt: Number.isFinite(Number(item.addedAt)) ? Number(item.addedAt) : Math.floor(Date.now() / 1000),
      }))
      .filter((item) => item.key);
  } catch (error) {
    console.error("failed to parse myNodes storage", error);
    return [];
  }
}

function saveMyNodes(items) {
  window.localStorage.setItem(myNodesStorageKey, JSON.stringify(items));
}

function inferMyNodeType(value) {
  const trimmed = String(value || "").trim();
  if (/^[a-fA-F0-9]{64}$/.test(trimmed)) {
    return "txid";
  }
  if (looksLikeIpKey(trimmed)) {
    return "ip";
  }
  return "address";
}

function looksLikeIpKey(value) {
  if (!value) {
    return false;
  }
  if (/^\[[0-9a-fA-F:]+\](?::\d+)?$/.test(value)) {
    return true;
  }
  if (/^\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?$/.test(value)) {
    return true;
  }
  return /^[a-zA-Z0-9.-]+:\d+$/.test(value);
}

function normalizeMyNodeKey(type, value) {
  const trimmed = String(value || "").trim();
  if (!trimmed) {
    return "";
  }
  if (type === "txid") {
    return trimmed.toLowerCase();
  }
  if (type === "ip") {
    return normalizeIpKey(trimmed);
  }
  return trimmed;
}

function normalizeIpKey(value) {
  const trimmed = String(value || "").trim();
  if (!trimmed) {
    return "";
  }
  if (trimmed.startsWith("[")) {
    const endBracket = trimmed.indexOf("]");
    if (endBracket > 0) {
      const host = trimmed.slice(1, endBracket).toLowerCase();
      const rest = trimmed.slice(endBracket + 1);
      return `[${host}]${rest}`;
    }
  }
  const colonCount = (trimmed.match(/:/g) || []).length;
  if (colonCount === 1) {
    const parts = trimmed.split(":");
    return `${parts[0].toLowerCase()}:${parts[1]}`;
  }
  if (colonCount > 1) {
    return trimmed.toLowerCase();
  }
  return trimmed.toLowerCase();
}

function ipHostOnly(value) {
  const normalized = normalizeIpKey(value);
  if (!normalized) {
    return "";
  }
  if (normalized.startsWith("[")) {
    const endBracket = normalized.indexOf("]");
    return endBracket > 0 ? normalized.slice(0, endBracket + 1) : normalized;
  }
  const colonCount = (normalized.match(/:/g) || []).length;
  if (colonCount === 1) {
    return normalized.split(":")[0];
  }
  return normalized;
}

function buildMasternodeLookup(items) {
  const addressMap = new Map();
  const txidMap = new Map();
  const ipMap = new Map();

  (items || []).forEach((item) => {
    if (item.addr) {
      addressMap.set(normalizeMyNodeKey("address", item.addr), item);
    }
    if (item.txid) {
      txidMap.set(normalizeMyNodeKey("txid", item.txid), item);
    }
    if (item.ip) {
      const exactKey = normalizeMyNodeKey("ip", item.ip);
      if (exactKey) {
        ipMap.set(exactKey, item);
      }
      const hostKey = ipHostOnly(item.ip);
      if (hostKey && !ipMap.has(hostKey)) {
        ipMap.set(hostKey, item);
      }
    }
  });

  return { addressMap, txidMap, ipMap };
}

function resolveMyNode(node, lookup) {
  const normalizedKey = normalizeMyNodeKey(node.type, node.key);
  if (!normalizedKey) {
    return { node, match: null };
  }

  let match = null;
  if (node.type === "address") {
    match = lookup.addressMap.get(normalizedKey) || null;
  } else if (node.type === "txid") {
    match = lookup.txidMap.get(normalizedKey) || null;
  } else if (node.type === "ip") {
    match = lookup.ipMap.get(normalizedKey) || lookup.ipMap.get(ipHostOnly(normalizedKey)) || null;
  }
  return { node, match };
}

function myNodeStatus(match) {
  if (!match) {
    return { label: "Not Found", className: "missing" };
  }
  const status = String(match.status || "").toUpperCase();
  const fallbackOnly = match.fallback_only === true;
  const staleFallback = fallbackOnly && match.lastseen && (Math.floor(Date.now() / 1000) - Number(match.lastseen)) > 86400;

  if (staleFallback) {
    return { label: "Unconfirmed", className: "warning" };
  }
  if (status === "ENABLED") {
    return { label: "Active", className: "active" };
  }
  if (status === "PRE_ENABLED") {
    return { label: "Starting", className: "starting" };
  }
  if (status === "EXPIRED" || status === "WATCHDOG_EXPIRED") {
    return { label: "Warning", className: "warning" };
  }
  if (status === "NEW_START_REQUIRED" || status === "POSE_BAN") {
    return { label: "Offline", className: "offline" };
  }
  if (status) {
    return { label: status, className: "missing" };
  }
  return { label: "Unknown", className: "missing" };
}

function formatNodeVersion(match) {
  if (!match) {
    return "-";
  }
  if (typeof match.subver === "string" && match.subver.trim()) {
    const cleaned = match.subver.match(/(\d+(?:\.\d+)+)/);
    return cleaned ? cleaned[1] : match.subver.trim();
  }
  if (match.version !== null && match.version !== undefined) {
    return String(match.version);
  }
  return "-";
}

function isMasternodeCompatible(match, targetVersion) {
  try {
    if (!match) {
      return null;
    }
    let subver = match.subver;
    if (typeof subver === "string" && subver.trim()) {
      const matchVer = subver.match(/(\d+(?:\.\d+)+)/);
      if (matchVer) {
        const parts = matchVer[1].split(".").map(Number);
        const targetStr = typeof targetVersion === "string" ? targetVersion : "2.9.0.2";
        const targetParts = targetStr.split(".").map(Number);
        for (let i = 0; i < Math.max(parts.length, targetParts.length); i++) {
          const part = parts[i] || 0;
          const target = targetParts[i] || 0;
          if (part > target) return true;
          if (part < target) return false;
        }
        return true;
      }
    }
  } catch (err) {
    console.error("isMasternodeCompatible error", err);
  }
  return null;
}

function renderMyNodes(payload = latestMasternodesPayload) {
  const body = byId("my-nodes-table-body");
  const listMeta = byId("my-nodes-list-generated-at");
  const nodes = loadMyNodes();
  const lookupKey = buildSignature([payload.list_generated_at_unix || 0, payload.items || []]);
  if (!cachedMasternodeLookup || lookupKey !== cachedMasternodeLookupKey) {
    cachedMasternodeLookup = buildMasternodeLookup(payload.items || []);
    cachedMasternodeLookupKey = lookupKey;
  }
  const lookup = cachedMasternodeLookup;
  const resolved = nodes.map((node) => resolveMyNode(node, lookup));

  let metaText = "Last MN sync: unavailable";
  if (payload.list_generated_at) {
    metaText = `Last MN sync: ${formatRelativeTime(payload.list_generated_at)} (${formatAbsoluteUtc(payload.list_generated_at)})`;
  }
  if (payload.stale) {
    metaText = `${metaText} [stale]`;
  }
  listMeta.textContent = metaText;

  body.innerHTML = "";
  if (!resolved.length) {
    const row = document.createElement("tr");
    row.innerHTML = "<td colspan='8' class='empty-state'>No nodes added</td>";
    body.appendChild(row);
    return;
  }

  resolved.forEach(({ node, match }, index) => {
    const status = myNodeStatus(match);
    let compatLabel = "-";
    let compatClass = "unknown";
    if (match) {
      const isCompat = isMasternodeCompatible(match, latestSnapshotTargetVersion);
      if (isCompat === true) {
        compatLabel = "Compatible";
        compatClass = "latest";
      } else if (isCompat === false) {
        compatLabel = "Legacy";
        compatClass = "legacy";
      } else {
        compatLabel = "Unknown";
        compatClass = "unknown";
      }
    }
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>
        <div class="node-label">${escapeHtml(node.label)}</div>
        <div class="node-key">${escapeHtml(node.key)}</div>
      </td>
      <td><span class="node-state node-state-${status.className}">${escapeHtml(status.label)}</span></td>
      <td>${match ? formatUnixRelativeTime(match.lastseen) : "-"}</td>
      <td>${escapeHtml(formatNodeVersion(match))}</td>
      <td>-</td>
      <td><span class="version-tag ${compatClass}">${compatLabel}</span></td>
      <td>${escapeHtml(match?.ip || "-")}</td>
      <td><button type="button" class="remove-node-button" data-node-index="${index}" aria-label="Remove node">x</button></td>
    `;
    body.appendChild(row);
  });
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function setMyNodesMessage(message, tone = "info") {
  const element = byId("my-nodes-message");
  element.textContent = message || "";
  element.className = `my-nodes-message ${message ? `is-${tone}` : ""}`.trim();
}

function nextDefaultLabel(items) {
  return `My Node ${items.length + 1}`;
}

function handleAddMyNode() {
  const keyInput = byId("my-nodes-key");
  const labelInput = byId("my-nodes-label");
  const rawKey = keyInput.value.trim();
  if (!rawKey) {
    setMyNodesMessage("Enter an address, txid, or ip.", "warning");
    return;
  }

  const type = inferMyNodeType(rawKey);
  const normalizedKey = normalizeMyNodeKey(type, rawKey);
  const items = loadMyNodes();
  const duplicate = items.some((item) => item.type === type && normalizeMyNodeKey(item.type, item.key) === normalizedKey);
  if (duplicate) {
    setMyNodesMessage("Already added", "warning");
    return;
  }

  items.push({
    key: normalizedKey,
    type,
    label: labelInput.value.trim() || nextDefaultLabel(items),
    addedAt: Math.floor(Date.now() / 1000),
  });
  saveMyNodes(items);
  keyInput.value = "";
  labelInput.value = "";
  setMyNodesMessage("Node added", "success");
  renderMyNodes();
}

function handleRemoveMyNode(index) {
  const items = loadMyNodes();
  if (index < 0 || index >= items.length) {
    return;
  }
  items.splice(index, 1);
  saveMyNodes(items);
  setMyNodesMessage("Node removed", "info");
  renderMyNodes();
}

function initMyNodesControls() {
  if (myNodesInitialized) {
    return;
  }
  myNodesInitialized = true;

  byId("my-nodes-add").addEventListener("click", handleAddMyNode);
  byId("my-nodes-key").addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      handleAddMyNode();
    }
  });
  byId("my-nodes-label").addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      handleAddMyNode();
    }
  });
  byId("my-nodes-table-body").addEventListener("click", (event) => {
    const button = event.target.closest(".remove-node-button");
    if (!button) {
      return;
    }
    handleRemoveMyNode(Number(button.dataset.nodeIndex));
  });
  renderMyNodes();
}

async function fetchStatus() {
  const response = await fetch(statusUrl, { headers: { Accept: "application/json" } });
  if (!response.ok) {
    throw new Error(`status request failed: ${response.status}`);
  }
  return response.json();
}

async function fetchMasternodes() {
  const response = await fetch(masternodesUrl, { headers: { Accept: "application/json" } });
  if (!response.ok) {
    throw new Error(`masternodes request failed: ${response.status}`);
  }
  return response.json();
}

async function refreshStatus() {
  initMyNodesControls();
  try {
    const snapshot = await fetchStatus();
    renderSnapshot(snapshot);
  } catch (error) {
    console.error(error);
    byId("stale-indicator").classList.remove("hidden");
  }
}

async function refreshMasternodes() {
  initMyNodesControls();
  try {
    latestMasternodesPayload = await fetchMasternodes();
    renderMyNodes(latestMasternodesPayload);
  } catch (error) {
    console.error(error);
    latestMasternodesPayload = {
      ...latestMasternodesPayload,
      stale: true,
    };
    renderMyNodes(latestMasternodesPayload);
  }
}

async function bootstrap() {
  initMyNodesControls();
  await Promise.allSettled([refreshStatus(), refreshMasternodes()]);
  window.setInterval(refreshStatus, statusPollIntervalMs);
  window.setInterval(refreshMasternodes, masternodesPollIntervalMs);
}

bootstrap();
