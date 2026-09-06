const state = { data: null };

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => [...document.querySelectorAll(sel)];

function fmtPrice(n, currency = "RON") {
  if (n == null || Number.isNaN(Number(n))) return "—";
  return `${Number(n).toFixed(0)} ${currency || "RON"}`;
}

function fmtWhen(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function renderStats() {
  const run = state.data.run || {};
  const finds = state.data.finds || [];
  const keeps = finds.filter((f) => f.source === "keep" || f.value_band === "steal" || f.value_band === "hunt");
  const sellers = state.data.sellers || [];
  const cells = [
    ["Scored last run", run.scored ?? "—"],
    ["Index (DB)", state.data.meta?.indexed_count ?? "—"],
    ["Keeps on desk", keeps.length],
    ["Bundles", (state.data.bundles || []).length],
    ["Sellers tracked", sellers.length],
    ["Alerts last run", run.alerts ?? "—"],
    ["Seen keys", run.seen_keys ?? "—"],
  ];
  $("#stats").innerHTML = cells
    .map(([k, v]) => `<div class="stat"><div class="k">${k}</div><div class="v">${v}</div></div>`)
    .join("");
  const src = state.data.meta?.source || "local";
  const idxSrc = state.data.meta?.indexed_source
    ? ` · index via ${state.data.meta.indexed_source}`
    : "";
  $("#lede").textContent = run.finished_at
    ? `Last finished run ${fmtWhen(run.finished_at)} · data via ${src}${idxSrc}. Refresh after Actions finishes to pull new keeps.`
    : `Waiting for a finished run snapshot · data via ${src}${idxSrc}.`;
}

async function loadRuns() {
  try {
    const res = await fetch("/api/runs", { cache: "no-store" });
    if (!res.ok) return [];
    const data = await res.json();
    return data.runs || [];
  } catch {
    return [];
  }
}

function renderRun() {
  const run = state.data.run || {};
  const hist = run.score_histogram || {};
  const max = Math.max(1, ...Object.values(hist).map(Number), 1);
  const bars = Array.from({ length: 10 }, (_, i) => {
    const score = String(i + 1);
    const n = Number(hist[score] || 0);
    const h = Math.max(8, Math.round((n / max) * 100));
    return `<div class="bar" style="height:${h}px" title="${score}: ${n}"><strong>${n}</strong><span>${score}</span></div>`;
  }).join("");
  const gh = (state.runs || []).map((r) => `
    <div class="bundle-item">
      <span class="pill ${r.conclusion === "success" ? "steal" : r.status === "in_progress" || r.status === "queued" ? "hunt" : "skip"}">${escapeHtml(r.status)}${r.conclusion ? ` / ${escapeHtml(r.conclusion)}` : ""}</span>
      <div>
        <div class="title">${escapeHtml(r.display_title || r.event || "run")}</div>
        <span class="reason">${fmtWhen(r.created_at)} · ${escapeHtml(r.event || "")}</span>
      </div>
      <div>${r.html_url ? `<a class="link" href="${escapeAttr(r.html_url)}" target="_blank" rel="noreferrer">GitHub</a>` : ""}</div>
    </div>`).join("") || `<p class="reason">No GitHub Actions runs visible yet (set GITHUB_TOKEN + GITHUB_REPO on Vercel).</p>`;

  $("#run-root").innerHTML = `
    <div class="bundle">
      <h3>Last scoring snapshot</h3>
      <meta>finished ${fmtWhen(run.finished_at)} · scored ${run.scored ?? "—"} · solo keeps ${run.solo_keeps ?? "—"} · bundles ${run.bundles ?? "—"} · alerts ${run.alerts ?? "—"}</meta>
      <p class="reason">Score histogram (count per deal_score)</p>
      <div class="hist">${bars}</div>
    </div>
    <div class="bundle" style="margin-top:1rem">
      <h3>GitHub Actions</h3>
      <meta>Cron every 15m on GitHub · optional hourly Vercel cron → same workflow</meta>
      <div class="bundle-items">${gh}</div>
    </div>`;
}

function secret() {
  return ($("#dash-secret")?.value || sessionStorage.getItem("dashSecret") || "").trim();
}

function setOpsMsg(text, kind) {
  const el = $("#ops-msg");
  el.textContent = text || "";
  el.className = `ops-msg${kind ? ` ${kind}` : ""}`;
}

async function triggerHunt({ fullSweep = false } = {}) {
  const token = secret();
  if (!token) {
    setOpsMsg("Enter DASHBOARD_SECRET first (same value as on Vercel).", "err");
    return;
  }
  sessionStorage.setItem("dashSecret", token);
  $("#run-now").disabled = true;
  $("#run-sweep").disabled = true;
  setOpsMsg(fullSweep ? "Dispatching full sweep…" : "Dispatching hunt…");
  try {
    const res = await fetch("/api/trigger", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-dashboard-secret": token,
      },
      body: JSON.stringify({ full_sweep: fullSweep }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.message || data.error || `HTTP ${res.status}`);
    setOpsMsg(`Queued on GitHub (${data.repo} / ${data.workflow}). Check Runs tab.`, "ok");
    state.runs = await loadRuns();
    renderRun();
  } catch (err) {
    setOpsMsg(String(err.message || err), "err");
  } finally {
    $("#run-now").disabled = false;
    $("#run-sweep").disabled = false;
  }
}

async function load() {
  const res = await fetch("/api/dashboard", { cache: "no-store" });
  if (!res.ok) throw new Error(`API ${res.status}`);
  state.data = await res.json();
  state.runs = await loadRuns();
  renderAll();
  $("#pulse").hidden = false;
}

function fillWatchOptions() {
  const sel = $("#watch");
  const current = sel.value;
  const watches = state.data.watches || [];
  sel.innerHTML = `<option value="">All</option>` + watches.map((w) =>
    `<option value="${escapeAttr(w)}">${escapeHtml(w)}</option>`
  ).join("");
  sel.value = current;
}

function filteredFinds() {
  const q = ($("#q").value || "").trim().toLowerCase();
  const watch = $("#watch").value;
  const band = $("#band").value;
  const minScore = Number($("#minScore").value || 0);
  const source = $("#source").value;
  const sort = $("#sort").value;
  let rows = [...(state.data.finds || [])];
  rows = rows.filter((f) => {
    if (watch && f.watch !== watch) return false;
    if (band && f.value_band !== band) return false;
    if ((f.deal_score || 0) < minScore) return false;
    if (source && f.source !== source) return false;
    if (q) {
      const blob = `${f.title || ""} ${f.watch || ""} ${f.seller || ""} ${f.reason || ""}`.toLowerCase();
      if (!blob.includes(q)) return false;
    }
    return true;
  });
  rows.sort((a, b) => {
    switch (sort) {
      case "score-asc": return (a.deal_score || 0) - (b.deal_score || 0);
      case "price-asc": return (a.price_num ?? 1e12) - (b.price_num ?? 1e12);
      case "price-desc": return (b.price_num ?? -1) - (a.price_num ?? -1);
      case "date-desc": return String(b.kept_at || "").localeCompare(String(a.kept_at || ""));
      case "watch": return String(a.watch || "").localeCompare(String(b.watch || ""));
      case "score-desc":
      default:
        return (b.deal_score || 0) - (a.deal_score || 0)
          || (a.price_num ?? 1e12) - (b.price_num ?? 1e12);
    }
  });
  return rows;
}

function renderFinds() {
  const rows = filteredFinds();
  $("#finds-count").textContent = `${rows.length} listing${rows.length === 1 ? "" : "s"}`;
  $("#finds-body").innerHTML = rows.map((f) => {
    const seller = f.seller || (f.seller_id ? `#${f.seller_id}` : "—");
    const sellerCell = f.seller_id
      ? `<a class="link" href="https://www.vinted.ro/member/${f.seller_id}" target="_blank" rel="noreferrer">${escapeHtml(seller)}</a>`
      : escapeHtml(seller);
    return `<tr>
      <td class="score">${f.deal_score ?? "—"}</td>
      <td><span class="pill ${escapeAttr(f.value_band || "skip")}">${escapeHtml(f.value_band || "—")}</span>
          <span class="pill ${escapeAttr(f.source || "")}">${escapeHtml(f.source || "")}</span></td>
      <td><div class="title">${escapeHtml(f.title || "—")}</div>
          <span class="reason">${escapeHtml(f.reason || "")}</span></td>
      <td class="mono">${fmtPrice(f.price_num ?? f.price, f.currency)}</td>
      <td>${escapeHtml(f.watch || "—")}</td>
      <td>${sellerCell}</td>
      <td class="risk-${escapeAttr(f.scam_risk || "")}">${escapeHtml(f.scam_risk || "—")}</td>
      <td>${f.url ? `<a class="link" href="${escapeAttr(f.url)}" target="_blank" rel="noreferrer">Open</a>` : ""}</td>
    </tr>`;
  }).join("") || `<tr><td colspan="8">No finds match these filters.</td></tr>`;
}

function renderBundles() {
  const bundles = state.data.bundles || [];
  const root = $("#bundles-root");
  if (!bundles.length) {
    root.innerHTML = `<div class="empty">No wardrobe opportunities yet. Near hauls appear when a seller’s closet clears the fee gate; index near/bundles come from the Cockroach score cache when the same seller has multiple hunt-fits; value hauls when the model confirms a steal/hunt.</div>`;
    return;
  }
  root.innerHTML = `<div class="bundle-grid">${bundles.map((b) => {
    const kind = b.kind || "keep_bundle";
    const kindLabel =
      kind === "value_haul" ? "value haul" :
      kind === "near_haul" ? "near haul" :
      kind === "index_near_bundle" ? "index near" :
      kind === "index_keep_bundle" ? "index bundle" :
      "keep bundle";
    const pillClass =
      kind === "value_haul" ? "haul" :
      kind === "near_haul" || kind === "index_near_bundle" ? "near" :
      kind === "index_keep_bundle" ? "keep" :
      "keep";
    const per = b.effective_price_per_useful_item != null
      ? ` · ~${Number(b.effective_price_per_useful_item).toFixed(0)} RON/item`
      : "";
    const offer = b.suggested_offer_ron != null
      ? ` · <strong>offer ~${Number(b.suggested_offer_ron).toFixed(0)} RON</strong>${b.offer_weak ? " <span class=\"pill near\">weak</span>" : ""}`
      : "";
    const reason = b.reason ? ` · ${escapeHtml(b.reason)}` : "";
    const items = (b.items || []).map((it) => `
      <div class="bundle-item">
        <span class="pill ${it.role === "keep" ? "keep" : "hunt"}">${escapeHtml(it.role || "")}</span>
        <div>
          <div class="title">${escapeHtml(it.title || "")}</div>
          <span class="reason">${escapeHtml(it.watch || "")} · score ${it.deal_score ?? "—"}</span>
        </div>
        <div>
          <div class="mono">${fmtPrice(it.price)}</div>
          ${it.url ? `<a class="link" href="${escapeAttr(it.url)}" target="_blank" rel="noreferrer">Open</a>` : ""}
        </div>
      </div>`).join("");
    const profile = b.seller_id
      ? `<a class="link" href="https://www.vinted.ro/member/${b.seller_id}" target="_blank" rel="noreferrer">${escapeHtml(b.seller || b.seller_id)}</a>`
      : escapeHtml(b.seller || "seller");
    return `<article class="bundle">
      <h3>${profile} <span class="pill ${pillClass}">${kindLabel}</span></h3>
      <meta>${escapeHtml(b.country || "?")} · listings ${Number(b.listing_sum || 0).toFixed(0)} + extra ${b.checkout_extra_ron ?? "?"} = <strong>${Number(b.checkout_total || (Number(b.listing_sum || 0) + Number(b.checkout_extra_ron || 0))).toFixed(0)} RON</strong>${per}${offer}${reason} · ${fmtWhen(b.kept_at)}</meta>
      <div class="bundle-items">${items}</div>
    </article>`;
  }).join("")}</div>`;
}

function renderSellers() {
  const mode = $("#sellerSort").value;
  const rows = [...(state.data.sellers || [])];
  rows.sort((a, b) => {
    if (mode === "avg") return b.avg_score - a.avg_score;
    if (mode === "keeps") return b.keeps - a.keeps || b.best_score - a.best_score;
    if (mode === "listings") return b.listings - a.listings;
    return b.best_score - a.best_score || b.avg_score - a.avg_score;
  });
  $("#sellers-body").innerHTML = rows.map((s, i) => {
    const name = s.profile_url
      ? `<a class="link" href="${escapeAttr(s.profile_url)}" target="_blank" rel="noreferrer">${escapeHtml(s.seller)}</a>`
      : escapeHtml(s.seller);
    return `<tr>
      <td class="mono">${i + 1}</td>
      <td>${name}</td>
      <td class="score">${s.best_score}</td>
      <td class="mono">${s.avg_score}</td>
      <td>${s.keeps}</td>
      <td>${s.listings}</td>
      <td>${escapeHtml((s.country || "—").toUpperCase())}</td>
      <td>${escapeHtml((s.watches || []).slice(0, 3).join(", ") || "—")}</td>
      <td>${s.profile_url ? `<a class="link" href="${escapeAttr(s.profile_url)}" target="_blank" rel="noreferrer">Profile</a>` : ""}</td>
    </tr>`;
  }).join("") || `<tr><td colspan="9">No seller scores yet — appears once listings carry seller_id (after this sweep finishes / pool fills).</td></tr>`;
}

function renderAll() {
  fillWatchOptions();
  renderStats();
  renderFinds();
  renderBundles();
  renderSellers();
  renderRun();
}

function escapeHtml(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}
function escapeAttr(s) {
  return escapeHtml(s).replaceAll("'", "&#39;");
}

$$(".tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    $$(".tab").forEach((b) => b.classList.toggle("active", b === btn));
    $$(".panel").forEach((p) => p.classList.toggle("active", p.id === `panel-${btn.dataset.tab}`));
  });
});

["q", "watch", "band", "minScore", "source", "sort"].forEach((id) => {
  $(`#${id}`).addEventListener("input", renderFinds);
  $(`#${id}`).addEventListener("change", renderFinds);
});
$("#sellerSort").addEventListener("change", renderSellers);
$("#refresh").addEventListener("click", () => load().catch(console.error));
$("#run-now")?.addEventListener("click", () => triggerHunt({ fullSweep: false }));
$("#run-sweep")?.addEventListener("click", () => triggerHunt({ fullSweep: true }));
const saved = sessionStorage.getItem("dashSecret");
if (saved && $("#dash-secret")) $("#dash-secret").value = saved;
$("#dash-secret")?.addEventListener("change", () => {
  sessionStorage.setItem("dashSecret", $("#dash-secret").value.trim());
});

load().catch((err) => {
  $("#lede").textContent = `Failed to load snapshot: ${err.message}. Locally: uv run python scripts/serve_dashboard.py — or deploy to Vercel.`;
});
