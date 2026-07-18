(() => {
  const rootPath = document.body.dataset.rootPath || "";
  const endpoint = `${rootPath}/api/light-status`;
  const refreshMs = 30000;

  function escapeHtml(value) {
    return String(value ?? "-")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function formatLatency(value) {
    return Number.isFinite(Number(value)) ? `${Number(value).toFixed(2)} ms` : "-";
  }

  function formatCheckedAt(value) {
    if (!value) return "-";
    const date = new Date(Number(value) * 1000);
    return Number.isNaN(date.getTime()) ? "-" : date.toLocaleString();
  }

  function findServicesPanel() {
    const table = document.getElementById("public-sites");
    return table ? table.closest("article.panel") : null;
  }

  function ensurePanel() {
    let panel = document.getElementById("pepew-light-panel");
    if (panel) return panel;

    panel = document.createElement("article");
    panel.id = "pepew-light-panel";
    panel.className = "panel wide-panel";
    panel.innerHTML = `
      <div class="panel-heading">
        <div>
          <h2>PEPEW Light</h2>
          <span class="panel-kicker">Service, web wallet, and API status</span>
        </div>
        <span id="pepew-light-overall" class="version-tag unknown">checking</span>
      </div>
      <div class="table-wrap top-space">
        <table>
          <thead>
            <tr>
              <th>Endpoint</th>
              <th>Status</th>
              <th>HTTP</th>
              <th>Latency</th>
              <th>Last checked</th>
            </tr>
          </thead>
          <tbody id="pepew-light-endpoints">
            <tr><td colspan="5" class="empty-state">Checking PEPEW Light services…</td></tr>
          </tbody>
        </table>
      </div>
      <div class="inline-panel-section">
        <div class="panel-heading compact-heading">
          <h3>Light API Status</h3>
          <a href="https://light.pepepow.net/api/status" target="_blank" rel="noopener noreferrer" class="panel-kicker">Open raw status</a>
        </div>
        <div id="pepew-light-api-summary" class="metric-grid summary-grid"></div>
        <details id="pepew-light-api-details" class="raw-snapshot-details top-space">
          <summary class="panel-kicker">Full API response</summary>
          <pre id="pepew-light-api-json" style="white-space: pre-wrap; overflow-wrap: anywhere;"></pre>
        </details>
      </div>
    `;

    const servicesPanel = findServicesPanel();
    if (servicesPanel?.parentElement) {
      servicesPanel.parentElement.insertBefore(panel, servicesPanel.nextSibling);
    } else {
      document.querySelector("main.shell")?.appendChild(panel);
    }
    return panel;
  }

  function flattenImportant(data) {
    if (!data || typeof data !== "object" || Array.isArray(data)) return [];
    const preferred = [
      "status", "service", "version", "network", "height", "block_height",
      "tip_height", "electrum_height", "daemon_height", "peers", "clients",
      "connections", "uptime", "uptime_seconds", "server", "backend",
      "electrumx", "wallet", "timestamp", "updated_at"
    ];
    const entries = Object.entries(data);
    const ordered = [
      ...preferred.flatMap((key) => entries.filter(([name]) => name.toLowerCase() === key)),
      ...entries.filter(([name]) => !preferred.includes(name.toLowerCase())),
    ];
    const seen = new Set();
    return ordered.filter(([key, value]) => {
      if (seen.has(key) || value === null || value === undefined) return false;
      seen.add(key);
      return ["string", "number", "boolean"].includes(typeof value);
    }).slice(0, 8);
  }

  function render(payload) {
    ensurePanel();
    const overall = document.getElementById("pepew-light-overall");
    const endpoints = document.getElementById("pepew-light-endpoints");
    const summary = document.getElementById("pepew-light-api-summary");
    const json = document.getElementById("pepew-light-api-json");

    const healthy = payload?.overall_status === "ok";
    if (overall) {
      overall.textContent = payload?.overall_status || "unknown";
      overall.className = `version-tag ${healthy ? "latest" : "unknown"}`;
    }

    if (endpoints) {
      endpoints.innerHTML = "";
      (payload?.endpoints || []).forEach((item) => {
        const row = document.createElement("tr");
        row.innerHTML = `
          <td><a href="${escapeHtml(item.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(item.name)}</a></td>
          <td><span class="version-tag ${item.ok ? "latest" : "legacy"}">${item.ok ? "ok" : "down"}</span></td>
          <td>${escapeHtml(item.status_code)}</td>
          <td>${formatLatency(item.latency_ms)}</td>
          <td>${formatCheckedAt(item.checked_at)}</td>
        `;
        endpoints.appendChild(row);
      });
    }

    const apiStatus = payload?.api_status;
    if (summary) {
      const important = flattenImportant(apiStatus);
      summary.innerHTML = important.length
        ? important.map(([key, value]) => `
            <div class="metric">
              <span class="label">${escapeHtml(key.replaceAll("_", " "))}</span>
              <strong>${escapeHtml(value)}</strong>
            </div>
          `).join("")
        : '<div class="list-item">No structured API status fields available.</div>';
    }
    if (json) {
      json.textContent = JSON.stringify(apiStatus ?? {}, null, 2);
    }
  }

  function renderError(error) {
    ensurePanel();
    const overall = document.getElementById("pepew-light-overall");
    const endpoints = document.getElementById("pepew-light-endpoints");
    if (overall) {
      overall.textContent = "unavailable";
      overall.className = "version-tag legacy";
    }
    if (endpoints) {
      endpoints.innerHTML = `<tr><td colspan="5" class="empty-state">${escapeHtml(error?.message || "Unable to load PEPEW Light status")}</td></tr>`;
    }
  }

  async function refresh() {
    try {
      const response = await fetch(endpoint, { cache: "no-store" });
      if (!response.ok) throw new Error(`Monitor API returned HTTP ${response.status}`);
      render(await response.json());
    } catch (error) {
      renderError(error);
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    ensurePanel();
    refresh();
    window.setInterval(refresh, refreshMs);
  });
})();
