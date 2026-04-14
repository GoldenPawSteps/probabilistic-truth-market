/* =================================================================
   PERPETUAL PROBABILISTIC TRUTH MARKET – Frontend Application
   ================================================================= */

const API = "";           // same-origin; empty prefix uses relative URLs
let currentUser = null;   // { id, name, balance }
let currentClaim = null;  // claim currently displayed in detail view
let distChart = null;
let qChart = null;

// ---------------------------------------------------------------------------
// Utility helpers
// ---------------------------------------------------------------------------

function fmt(n, digits = 6) {
  if (n === null || n === undefined) return "—";
  return Number(n).toFixed(digits);
}

function fmtShort(n) { return fmt(n, 4); }

function showError(el, msg) {
  el.textContent = msg;
  el.classList.remove("hidden");
}
function hideError(el) { el.classList.add("hidden"); }

async function apiFetch(path, opts = {}) {
  const resp = await fetch(API + path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  const data = await resp.json();
  if (!resp.ok) {
    const detail = data.detail;
    if (typeof detail === "object") throw new Error(detail.message || JSON.stringify(detail));
    throw new Error(detail || `HTTP ${resp.status}`);
  }
  return data;
}

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------

document.getElementById("btn-login").addEventListener("click", () => doAuth("login"));
document.getElementById("btn-register").addEventListener("click", () => doAuth("register"));
document.getElementById("auth-name").addEventListener("keydown", (e) => {
  if (e.key === "Enter") doAuth("login");
});

async function doAuth(mode) {
  const name = document.getElementById("auth-name").value.trim();
  const errEl = document.getElementById("auth-error");
  hideError(errEl);
  if (!name) { showError(errEl, "Please enter a username."); return; }

  try {
    const endpoint = mode === "login" ? "/api/login" : "/api/register";
    const user = await apiFetch(endpoint, {
      method: "POST",
      body: JSON.stringify({ name }),
    });
    setCurrentUser(user);
  } catch (e) {
    showError(errEl, e.message);
  }
}

function setCurrentUser(user) {
  currentUser = user;
  localStorage.setItem("userId", user.id);
  localStorage.setItem("userName", user.name);
  document.getElementById("auth-screen").classList.add("hidden");
  document.getElementById("app-screen").classList.remove("hidden");
  updateHeaderUser();
  showView("claims");
  loadClaims();
}

function updateHeaderUser() {
  document.getElementById("header-username").textContent = currentUser.name;
  document.getElementById("header-balance").textContent = fmtShort(currentUser.balance);
}

document.getElementById("btn-logout").addEventListener("click", () => {
  currentUser = null;
  localStorage.removeItem("userId");
  localStorage.removeItem("userName");
  document.getElementById("app-screen").classList.add("hidden");
  document.getElementById("auth-screen").classList.remove("hidden");
  document.getElementById("auth-name").value = "";
  hideError(document.getElementById("auth-error"));
});

// Auto-login from localStorage
window.addEventListener("DOMContentLoaded", async () => {
  const userId = localStorage.getItem("userId");
  if (userId) {
    try {
      const user = await apiFetch(`/api/users/${userId}`);
      setCurrentUser(user);
    } catch (_) {
      localStorage.removeItem("userId");
      localStorage.removeItem("userName");
    }
  }
});

// ---------------------------------------------------------------------------
// Navigation
// ---------------------------------------------------------------------------

document.querySelectorAll(".nav-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    const view = btn.dataset.view;
    document.querySelectorAll(".nav-btn").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    if (view === "claims") {
      showView("claims");
      loadClaims();
    } else if (view === "positions") {
      showView("positions");
      loadPositions();
    }
  });
});

document.getElementById("btn-back").addEventListener("click", () => {
  showView("claims");
  loadClaims();
  setNavActive("claims");
});

function showView(name) {
  document.querySelectorAll(".view").forEach((v) => v.classList.add("hidden"));
  document.getElementById(`view-${name === "claim-detail" ? "claim-detail" : name}`).classList.remove("hidden");
  document.getElementById("page-title").textContent =
    name === "claims" ? "All Claims" :
    name === "positions" ? "My Positions" :
    (currentClaim ? currentClaim.name : "Claim Detail");
}

function setNavActive(name) {
  document.querySelectorAll(".nav-btn").forEach((b) => {
    b.classList.toggle("active", b.dataset.view === name);
  });
}

// ---------------------------------------------------------------------------
// Claims List
// ---------------------------------------------------------------------------

document.getElementById("claims-search").addEventListener("input", filterClaims);

let allClaims = [];

async function loadClaims() {
  try {
    allClaims = await apiFetch("/api/claims");
    renderClaims(allClaims);
  } catch (e) {
    console.error("Failed to load claims", e);
  }
}

function filterClaims() {
  const q = document.getElementById("claims-search").value.toLowerCase();
  const filtered = q ? allClaims.filter((c) => c.name.toLowerCase().includes(q) || (c.description || "").toLowerCase().includes(q)) : allClaims;
  renderClaims(filtered);
}

function renderClaims(claims) {
  const list = document.getElementById("claims-list");
  const empty = document.getElementById("claims-empty");
  list.innerHTML = "";
  if (!claims.length) {
    empty.classList.remove("hidden");
    return;
  }
  empty.classList.add("hidden");
  claims.forEach((claim) => {
    const card = document.createElement("div");
    card.className = "claim-card";
    card.innerHTML = `
      <h4>${escHtml(claim.name)}</h4>
      <div class="card-meta">${claim.omega.length} outcomes &nbsp;|&nbsp; b = ${fmtShort(claim.b)}</div>
      ${claim.description ? `<p class="muted" style="margin-bottom:10px;font-size:12px;">${escHtml(claim.description)}</p>` : ""}
      <div class="card-stats">
        <div class="card-stat"><span class="label">C(q) </span><span class="value">${fmtShort(claim.current_cost)}</span></div>
        <div class="card-stat"><span class="label">log Z </span><span class="value">${fmtShort(claim.log_partition)}</span></div>
      </div>`;
    card.addEventListener("click", () => openClaimDetail(claim.id));
    list.appendChild(card);
  });
}

// ---------------------------------------------------------------------------
// Positions View
// ---------------------------------------------------------------------------

async function loadPositions() {
  try {
    const user = await apiFetch(`/api/users/${currentUser.id}`);
    currentUser.balance = user.balance;
    updateHeaderUser();
    const positions = user.positions || [];
    const list = document.getElementById("positions-list");
    const empty = document.getElementById("positions-empty");
    list.innerHTML = "";
    if (!positions.length) {
      empty.classList.remove("hidden");
      return;
    }
    empty.classList.add("hidden");
    positions.forEach((pos) => {
      const card = document.createElement("div");
      card.className = "claim-card";
      const qt = pos.q_t_values;
      const minVal = Math.min(...qt).toFixed(4);
      const maxVal = Math.max(...qt).toFixed(4);
      card.innerHTML = `
        <h4>${escHtml(pos.claim_name)}</h4>
        <div class="card-meta">${pos.omega.length} outcomes &nbsp;|&nbsp; b = ${fmtShort(pos.b)}</div>
        <div class="card-stats">
          <div class="card-stat"><span class="label">q_t min </span><span class="value">${minVal}</span></div>
          <div class="card-stat"><span class="label">q_t max </span><span class="value">${maxVal}</span></div>
        </div>`;
      card.addEventListener("click", () => openClaimDetail(pos.claim_id));
      list.appendChild(card);
    });
  } catch (e) {
    console.error("Failed to load positions", e);
  }
}

// ---------------------------------------------------------------------------
// Claim Detail
// ---------------------------------------------------------------------------

async function openClaimDetail(claimId) {
  try {
    const claim = await apiFetch(`/api/claims/${claimId}`);
    currentClaim = claim;
    renderClaimDetail(claim);
    showView("claim-detail");
  } catch (e) {
    console.error("Failed to load claim", e);
  }
}

function renderClaimDetail(claim) {
  document.getElementById("detail-claim-name").textContent = claim.name;
  document.getElementById("detail-b").textContent = fmtShort(claim.b);
  document.getElementById("detail-cost").textContent = fmtShort(claim.current_cost);
  document.getElementById("detail-log-partition").textContent = fmtShort(claim.log_partition);
  document.getElementById("detail-n-outcomes").textContent = claim.omega.length;
  document.getElementById("detail-description").textContent = claim.description || "";

  renderDistChart(claim);
  renderQChart(claim);
  renderDeltaQInputs(claim);
  renderMyPosition(claim);

  // Reset trade UI
  document.getElementById("trade-preview").classList.add("hidden");
  document.getElementById("trade-success").classList.add("hidden");
  document.getElementById("trade-error").classList.add("hidden");
  document.getElementById("btn-execute-trade").classList.add("hidden");
}

// ── Distribution chart (prior P vs implied Q)
function renderDistChart(claim) {
  const labels = claim.omega.map((o) => String(o).slice(0, 20));
  const priorData = claim.probabilities;
  const impliedData = claim.implied_probs;

  if (distChart) { distChart.destroy(); distChart = null; }
  const ctx = document.getElementById("dist-chart").getContext("2d");
  distChart = new Chart(ctx, {
    type: "bar",
    data: {
      labels,
      datasets: [
        {
          label: "Prior P(ω)",
          data: priorData,
          backgroundColor: "rgba(79,124,255,0.7)",
          borderColor: "rgba(79,124,255,1)",
          borderWidth: 1,
        },
        {
          label: "Implied Q(ω)",
          data: impliedData,
          backgroundColor: "rgba(45,202,115,0.7)",
          borderColor: "rgba(45,202,115,1)",
          borderWidth: 1,
        },
      ],
    },
    options: chartOptions("Probability"),
  });
}

// ── q-values chart
function renderQChart(claim) {
  const labels = claim.omega.map((o) => String(o).slice(0, 20));
  if (qChart) { qChart.destroy(); qChart = null; }
  const ctx = document.getElementById("q-chart").getContext("2d");
  qChart = new Chart(ctx, {
    type: "bar",
    data: {
      labels,
      datasets: [
        {
          label: "q(ω)",
          data: claim.q_values,
          backgroundColor: "rgba(240,160,48,0.7)",
          borderColor: "rgba(240,160,48,1)",
          borderWidth: 1,
        },
      ],
    },
    options: chartOptions("q value"),
  });
}

function chartOptions(yLabel) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        labels: { color: "#7b82a8", font: { size: 11 } },
      },
    },
    scales: {
      x: {
        ticks: { color: "#7b82a8", font: { size: 10 }, maxRotation: 45 },
        grid: { color: "rgba(46,51,82,0.5)" },
      },
      y: {
        title: { display: true, text: yLabel, color: "#7b82a8", font: { size: 11 } },
        ticks: { color: "#7b82a8", font: { size: 11 } },
        grid: { color: "rgba(46,51,82,0.5)" },
      },
    },
  };
}

// ── Delta-q input rows
function renderDeltaQInputs(claim) {
  const container = document.getElementById("delta-q-inputs");
  container.innerHTML = "";
  claim.omega.forEach((outcome, i) => {
    const row = document.createElement("div");
    row.className = "delta-row";
    row.innerHTML = `
      <span class="delta-label" title="${escHtml(String(outcome))}">
        ${escHtml(String(outcome).slice(0, 24))}
        <small class="muted"> (p=${fmtShort(claim.probabilities[i])})</small>
      </span>
      <input class="delta-input" type="number" value="0" step="0.1"
             data-index="${i}" id="dq-${i}" />`;
    container.appendChild(row);
  });
}

// ── My position table
async function renderMyPosition(claim) {
  const content = document.getElementById("my-position-content");
  try {
    const user = await apiFetch(`/api/users/${currentUser.id}`);
    currentUser.balance = user.balance;
    updateHeaderUser();
    const pos = (user.positions || []).find((p) => p.claim_id === claim.id);
    if (!pos) {
      content.innerHTML = '<p class="muted">No position on this claim yet.</p>';
      return;
    }
    const rows = claim.omega.map((o, i) => {
      const v = pos.q_t_values[i];
      const cls = v > 0 ? "pos-positive" : v < 0 ? "pos-negative" : "";
      return `<tr><td>${escHtml(String(o))}</td><td class="${cls}">${fmt(v)}</td></tr>`;
    }).join("");
    content.innerHTML = `
      <table class="position-table">
        <thead><tr><th>Outcome</th><th>q_t(ω)</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>`;
  } catch (e) {
    content.innerHTML = '<p class="muted">Could not load position.</p>';
  }
}

// ---------------------------------------------------------------------------
// Trade interface
// ---------------------------------------------------------------------------

document.getElementById("btn-preset-zero").addEventListener("click", () => {
  if (!currentClaim) return;
  currentClaim.omega.forEach((_, i) => {
    const inp = document.getElementById(`dq-${i}`);
    if (inp) inp.value = "0";
  });
  document.getElementById("trade-preview").classList.add("hidden");
  document.getElementById("trade-success").classList.add("hidden");
  document.getElementById("trade-error").classList.add("hidden");
});

document.getElementById("btn-preset-uniform").addEventListener("click", () => {
  if (!currentClaim) return;
  currentClaim.omega.forEach((_, i) => {
    const inp = document.getElementById(`dq-${i}`);
    if (inp) inp.value = "0.1";
  });
});

document.getElementById("btn-preview-trade").addEventListener("click", previewTrade);
document.getElementById("btn-execute-trade").addEventListener("click", executeTrade);

function getDeltaQ() {
  if (!currentClaim) return null;
  return currentClaim.omega.map((_, i) => {
    const v = parseFloat(document.getElementById(`dq-${i}`)?.value || "0");
    return isNaN(v) ? 0 : v;
  });
}

async function previewTrade() {
  if (!currentClaim || !currentUser) return;
  const deltaQ = getDeltaQ();
  const previewEl = document.getElementById("trade-preview");
  const errEl = document.getElementById("trade-error");
  const successEl = document.getElementById("trade-success");
  successEl.classList.add("hidden");
  errEl.classList.add("hidden");

  try {
    const result = await apiFetch(`/api/claims/${currentClaim.id}/preview`, {
      method: "POST",
      body: JSON.stringify({ user_id: currentUser.id, delta_q: deltaQ }),
    });

    document.getElementById("prev-delta-c").textContent = fmt(result.delta_c);
    document.getElementById("prev-delta-inf").textContent = fmt(result.delta_inf);
    document.getElementById("prev-required").textContent = fmt(result.required_collateral);
    document.getElementById("prev-current-balance").textContent = fmt(result.current_balance);

    const executeBtn = document.getElementById("btn-execute-trade");
    const validMsg = document.getElementById("prev-valid-msg");
    const invalidMsg = document.getElementById("prev-invalid-msg");

    if (result.valid) {
      document.getElementById("prev-new-balance").textContent = fmt(result.new_balance);
      validMsg.classList.remove("hidden");
      invalidMsg.classList.add("hidden");
      executeBtn.classList.remove("hidden");
    } else {
      document.getElementById("prev-new-balance").textContent = "—";
      validMsg.classList.add("hidden");
      invalidMsg.classList.remove("hidden");
      executeBtn.classList.add("hidden");
    }

    previewEl.classList.remove("hidden");
  } catch (e) {
    showError(errEl, "Preview failed: " + e.message);
  }
}

async function executeTrade() {
  if (!currentClaim || !currentUser) return;
  const deltaQ = getDeltaQ();
  const errEl = document.getElementById("trade-error");
  const successEl = document.getElementById("trade-success");
  errEl.classList.add("hidden");

  try {
    const result = await apiFetch(`/api/claims/${currentClaim.id}/trade`, {
      method: "POST",
      body: JSON.stringify({ user_id: currentUser.id, delta_q: deltaQ }),
    });

    currentUser.balance = result.new_balance;
    updateHeaderUser();

    // Update current claim data
    currentClaim = result.claim;

    // Re-render charts and position
    renderDistChart(currentClaim);
    renderQChart(currentClaim);
    document.getElementById("detail-cost").textContent = fmtShort(currentClaim.current_cost);
    document.getElementById("detail-log-partition").textContent = fmtShort(currentClaim.log_partition);

    await renderMyPosition(currentClaim);

    // Reset delta-q inputs
    currentClaim.omega.forEach((_, i) => {
      const inp = document.getElementById(`dq-${i}`);
      if (inp) inp.value = "0";
    });

    document.getElementById("trade-preview").classList.add("hidden");
    document.getElementById("btn-execute-trade").classList.add("hidden");
    successEl.classList.remove("hidden");
    setTimeout(() => successEl.classList.add("hidden"), 3000);
  } catch (e) {
    showError(errEl, "Trade failed: " + e.message);
  }
}

// ---------------------------------------------------------------------------
// Create Claim Modal
// ---------------------------------------------------------------------------

document.getElementById("btn-create-claim").addEventListener("click", openCreateModal);
document.getElementById("btn-cancel-claim").addEventListener("click", closeCreateModal);
document.getElementById("modal-close").addEventListener("click", closeCreateModal);
document.querySelector(".modal-backdrop").addEventListener("click", closeCreateModal);

document.getElementById("claim-space-type").addEventListener("change", function () {
  const t = this.value;
  document.getElementById("space-uniform").classList.toggle("hidden", t === "custom");
  document.getElementById("space-custom").classList.toggle("hidden", t !== "custom");
});

function openCreateModal() {
  document.getElementById("create-claim-modal").classList.remove("hidden");
  document.getElementById("claim-name").value = "";
  document.getElementById("claim-description").value = "";
  document.getElementById("claim-b").value = "1";
  document.getElementById("claim-space-type").value = "uniform";
  document.getElementById("space-uniform").classList.remove("hidden");
  document.getElementById("space-custom").classList.add("hidden");
  document.getElementById("uniform-n").value = "4";
  document.getElementById("custom-outcomes").value = "";
  hideError(document.getElementById("claim-form-error"));
}

function closeCreateModal() {
  document.getElementById("create-claim-modal").classList.add("hidden");
}

document.getElementById("btn-submit-claim").addEventListener("click", submitCreateClaim);

async function submitCreateClaim() {
  const errEl = document.getElementById("claim-form-error");
  hideError(errEl);

  const name = document.getElementById("claim-name").value.trim();
  if (!name) { showError(errEl, "Claim name is required."); return; }

  const b = parseFloat(document.getElementById("claim-b").value);
  if (isNaN(b) || b <= 0) { showError(errEl, "Liquidity b must be positive."); return; }

  const spaceType = document.getElementById("claim-space-type").value;
  let omega = [];
  let probabilities = [];

  if (spaceType === "binary") {
    omega = ["Yes", "No"];
    probabilities = [0.5, 0.5];
  } else if (spaceType === "uniform") {
    const n = parseInt(document.getElementById("uniform-n").value);
    if (isNaN(n) || n < 2) { showError(errEl, "N must be at least 2."); return; }
    omega = Array.from({ length: n }, (_, i) => `Outcome ${i + 1}`);
    probabilities = Array(n).fill(1 / n);
  } else {
    // custom
    const lines = document.getElementById("custom-outcomes").value.trim().split("\n").filter((l) => l.trim());
    if (lines.length < 2) { showError(errEl, "At least 2 outcomes required."); return; }
    for (const line of lines) {
      const parts = line.split(",").map((s) => s.trim());
      if (parts.length < 2) { showError(errEl, `Invalid line: "${line}". Use format: label, probability`); return; }
      const p = parseFloat(parts[parts.length - 1]);
      if (isNaN(p) || p <= 0) { showError(errEl, `Invalid probability in line: "${line}"`); return; }
      omega.push(parts.slice(0, -1).join(",").trim());
      probabilities.push(p);
    }
    const total = probabilities.reduce((a, b) => a + b, 0);
    if (Math.abs(total - 1.0) > 1e-4) {
      showError(errEl, `Probabilities sum to ${total.toFixed(6)}, must be 1.0 (±0.0001).`);
      return;
    }
    // Normalize to ensure exact sum-to-1 (matches backend normalization)
    probabilities = probabilities.map((p) => p / total);
  }

  const description = document.getElementById("claim-description").value.trim();

  try {
    const claim = await apiFetch("/api/claims", {
      method: "POST",
      body: JSON.stringify({
        user_id: currentUser.id,
        name,
        description,
        omega,
        probabilities,
        b,
      }),
    });
    closeCreateModal();
    allClaims.unshift(claim);
    openClaimDetail(claim.id);
    setNavActive("claims");
  } catch (e) {
    showError(errEl, e.message);
  }
}

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------

function escHtml(str) {
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}
