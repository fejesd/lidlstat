"use strict";

const $ = (sel) => document.querySelector(sel);
const DAYS = ["H", "K", "Sze", "Cs", "P", "Szo", "V"];
const DAYS_LONG = ["hétfő", "kedd", "szerda", "csütörtök", "péntek", "szombat", "vasárnap"];

const state = {
  period: "12m",
  topBy: "spend",
  currency: "HUF",
  receiptOffset: 0,
  charts: {},
};

// ---------- helpers ----------

function storage(key, value) {
  try {
    if (value === undefined) return localStorage.getItem(key);
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch { /* private mode etc. */ }
  return null;
}

function money(v, digits = 0) {
  return new Intl.NumberFormat("hu-HU", {
    style: "currency", currency: state.currency || "HUF",
    maximumFractionDigits: digits, minimumFractionDigits: 0,
  }).format(v || 0);
}
const num = (v, d = 0) => new Intl.NumberFormat("hu-HU", { maximumFractionDigits: d }).format(v || 0);

function fmtDate(iso, withTime = true) {
  const d = new Date(iso);
  const opts = { year: "numeric", month: "short", day: "numeric" };
  if (withTime) Object.assign(opts, { hour: "2-digit", minute: "2-digit" });
  return d.toLocaleString("hu-HU", opts);
}

function isoDay(d) {
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

function periodParams() {
  const now = new Date();
  const start = new Date(now);
  switch (state.period) {
    case "30d": start.setDate(now.getDate() - 29); break;
    case "3m": start.setMonth(now.getMonth() - 3); break;
    case "12m": start.setFullYear(now.getFullYear() - 1); break;
    case "ytd": start.setMonth(0, 1); break;
    default: return "";
  }
  return `start=${isoDay(start)}`;
}

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k === "style") node.style.cssText = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  for (const c of children) node.append(c);
  return node;
}

async function api(path, opts = {}) {
  const headers = { ...(opts.headers || {}) };
  const token = storage("appToken");
  if (token) headers["X-App-Token"] = token;
  const res = await fetch(path, { ...opts, headers });
  if (res.status === 401) {
    await askToken();
    return api(path, opts);
  }
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

function askToken() {
  return new Promise((resolve) => {
    const dlg = $("#token-dialog");
    dlg.addEventListener("close", () => {
      storage("appToken", $("#token-input").value);
      resolve();
    }, { once: true });
    dlg.showModal();
  });
}

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

// ---------- charts ----------

function baseChartOptions() {
  const text = cssVar("--text-2");
  const grid = cssVar("--grid");
  return {
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: { display: false },
      tooltip: { displayColors: false },
    },
    scales: {
      x: { grid: { display: false }, ticks: { color: text, maxRotation: 0, autoSkipPadding: 8 } },
      y: {
        beginAtZero: true, border: { display: false },
        grid: { color: grid }, ticks: { color: text, maxTicksLimit: 5 },
      },
    },
  };
}

function drawChart(id, config) {
  state.charts[id]?.destroy();
  state.charts[id] = new Chart(document.getElementById(id), config);
}

function renderMonthly(rows) {
  const multiYear = new Set(rows.map((r) => r.month.slice(0, 4))).size > 1;
  const labels = rows.map((r) => {
    const [y, m] = r.month.split("-");
    const label = new Date(+y, +m - 1, 1).toLocaleString("hu-HU", { month: "short" });
    return multiYear ? `${label} '${y.slice(2)}` : label;
  });
  const opts = baseChartOptions();
  opts.plugins.tooltip.callbacks = {
    title: (items) => rows[items[0].dataIndex].month,
    label: (item) => {
      const r = rows[item.dataIndex];
      return [`Költés: ${money(r.spend)}`, `Vásárlás: ${r.receipts}`, `Megtakarítás: ${money(r.savings)}`];
    },
  };
  opts.scales.y.ticks.callback = (v) => num(v);
  drawChart("monthly-chart", {
    type: "bar",
    data: {
      labels,
      datasets: [{
        data: rows.map((r) => r.spend),
        backgroundColor: cssVar("--series"),
        borderRadius: { topLeft: 4, topRight: 4 },
        borderSkipped: "bottom",
        maxBarThickness: 28,
      }],
    },
    options: opts,
  });
  const table = $("#monthly-table");
  table.replaceChildren(
    el("tr", {}, el("th", {}, "Hónap"), el("th", {}, "Költés"), el("th", {}, "Vásárlás")),
    ...rows.map((r) => el("tr", {}, el("td", {}, r.month), el("td", {}, money(r.spend)), el("td", {}, String(r.receipts)))),
  );
}

function renderHeatmap(rows) {
  const hours = rows.map((r) => r.hour);
  const minH = Math.min(7, ...hours);
  const maxH = Math.max(21, ...hours);
  const cols = maxH - minH + 1;
  const grid = $("#heatmap");
  grid.style.setProperty("--cols", cols);
  const counts = new Map(rows.map((r) => [`${r.weekday}-${r.hour}`, r]));
  const max = Math.max(1, ...rows.map((r) => r.receipts));
  const nodes = [el("span")];
  for (let h = minH; h <= maxH; h++) {
    nodes.push(el("span", { class: "hlabel" }, h % 3 === 0 ? String(h) : ""));
  }
  for (let d = 0; d < 7; d++) {
    nodes.push(el("span", { class: "dlabel" }, DAYS[d]));
    for (let h = minH; h <= maxH; h++) {
      const r = counts.get(`${d}-${h}`);
      const n = r ? r.receipts : 0;
      const level = n === 0 ? 0 : Math.max(1, Math.ceil((n / max) * 6));
      const label = `${DAYS_LONG[d]} ${h}–${h + 1} óra: ${n} vásárlás${r ? `, ${money(r.spend)}` : ""}`;
      nodes.push(el("button", {
        type: "button", class: "cell", "aria-label": label, title: label,
        style: `background: var(--heat-${level})`,
        onclick: (e) => {
          grid.querySelectorAll("[aria-selected]").forEach((c) => c.removeAttribute("aria-selected"));
          e.currentTarget.setAttribute("aria-selected", "true");
          $("#heatmap-info").textContent = label[0].toUpperCase() + label.slice(1);
        },
      }));
    }
  }
  grid.replaceChildren(...nodes);
  const busiest = [...rows].sort((a, b) => b.receipts - a.receipts)[0];
  $("#heatmap-info").textContent = busiest
    ? `Legtöbbször ${DAYS_LONG[busiest.weekday]} ${busiest.hour} és ${busiest.hour + 1} óra között vásárolsz.`
    : "Nincs adat ebben az időszakban.";
}

function renderBarList(target, rows, valueOf, labelOf, nameOf, onPick) {
  const max = Math.max(1, ...rows.map(valueOf));
  target.replaceChildren(...rows.map((r) => {
    const inner = el("div", {},
      el("div", { class: "bar-row" },
        el("span", { class: "bar-name" }, nameOf(r)),
        el("span", { class: "bar-val" }, labelOf(r))),
      el("div", { class: "bar", style: `width:${Math.max(2, (valueOf(r) / max) * 100)}%` }));
    return el("li", {}, onPick ? el("button", { type: "button", onclick: () => onPick(r) }, inner) : inner);
  }));
  if (!rows.length) target.replaceChildren(el("li", { class: "muted small" }, "Nincs adat."));
}

async function loadTop() {
  const p = periodParams();
  const rows = await api(`/api/top-products?by=${state.topBy}&limit=15${p ? `&${p}` : ""}`);
  renderBarList(
    $("#top-list"), rows,
    (r) => (state.topBy === "spend" ? r.spend : r.purchases),
    (r) => (state.topBy === "spend" ? money(r.spend) : `${r.purchases}×`),
    (r) => r.name,
    (r) => showPrice(r.name),
  );
}

// ---------- price tracker ----------

let searchTimer;
$("#product-search").addEventListener("input", (e) => {
  clearTimeout(searchTimer);
  const q = e.target.value.trim();
  if (!q) { $("#product-suggest").replaceChildren(); return; }
  searchTimer = setTimeout(async () => {
    const rows = await api(`/api/products?q=${encodeURIComponent(q)}`);
    $("#product-suggest").replaceChildren(...rows.map((r) =>
      el("li", {}, el("button", { type: "button", onclick: () => showPrice(r.name) }, `${r.name} (${r.purchases}×)`))));
  }, 200);
});

async function showPrice(name) {
  $("#product-suggest").replaceChildren();
  $("#product-search").value = name;
  const rows = await api(`/api/products/history?name=${encodeURIComponent(name)}`);
  $("#price-panel").hidden = false;
  $("#price-title").textContent = name;
  const prices = rows.map((r) => r.unit_price).filter((v) => v != null);
  const unit = rows.some((r) => r.is_weight) ? " /kg" : "";
  const first = prices[0], last = prices[prices.length - 1];
  const change = first ? ((last - first) / first) * 100 : 0;
  $("#price-stats").replaceChildren(
    el("span", {}, "Utolsó: ", el("b", {}, money(last, 2) + unit)),
    el("span", {}, "Min: ", el("b", {}, money(Math.min(...prices), 2))),
    el("span", {}, "Max: ", el("b", {}, money(Math.max(...prices), 2))),
    el("span", {}, "Változás: ", el("b", {}, `${change > 0 ? "+" : ""}${num(change, 1)}%`)),
  );
  const opts = baseChartOptions();
  opts.scales.y.beginAtZero = false;
  opts.scales.y.ticks.callback = (v) => num(v);
  opts.plugins.tooltip.callbacks = {
    title: (items) => fmtDate(rows[items[0].dataIndex].date, false),
    label: (item) => {
      const r = rows[item.dataIndex];
      const parts = [`Egységár: ${money(r.unit_price, 2)}${unit}`];
      if (r.discount) parts.push(`Kedvezmény: ${money(r.discount, 2)}`);
      return parts;
    },
  };
  drawChart("price-chart", {
    type: "line",
    data: {
      labels: rows.map((r) => new Date(r.date).toLocaleDateString("hu-HU", { year: "2-digit", month: "short" })),
      datasets: [{
        data: rows.map((r) => r.unit_price),
        borderColor: cssVar("--series"), backgroundColor: cssVar("--series"),
        borderWidth: 2, pointRadius: rows.length > 30 ? 0 : 4, pointHoverRadius: 6,
        stepped: "before",
      }],
    },
    options: opts,
  });
  $("#price-panel").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

// ---------- receipts ----------

async function loadReceipts(reset) {
  if (reset) { state.receiptOffset = 0; $("#receipt-list").replaceChildren(); }
  const p = periodParams();
  const rows = await api(`/api/receipts?limit=20&offset=${state.receiptOffset}${p ? `&${p}` : ""}`);
  state.receiptOffset += rows.length;
  $("#more-receipts").hidden = rows.length < 20;
  for (const r of rows) {
    const li = el("li");
    const btn = el("button", { type: "button", "aria-expanded": "false" },
      el("div", { class: "receipt-meta" },
        el("span", {}, fmtDate(r.date)),
        el("span", { class: "muted small" }, `${r.store_name || "Lidl"} · ${r.items} tétel`)),
      el("div", { class: "receipt-total" },
        el("span", {}, money(r.total)),
        r.discount ? el("span", { class: "muted small", style: "display:block" }, `−${money(r.discount)}`) : "",
        r.mismatched ? el("span", { class: "small", style: "display:block", title: "A tételek összege eltér a végösszegtől" }, "⚠ ellenőrizendő") : ""));
    btn.addEventListener("click", async () => {
      const open = btn.getAttribute("aria-expanded") === "true";
      btn.setAttribute("aria-expanded", String(!open));
      li.querySelector(".receipt-items")?.remove();
      if (open) return;
      const items = await api(`/api/receipts/${encodeURIComponent(r.id)}/items`);
      const list = el("ul", { class: "receipt-items" }, ...items.map((it) => el("li", {},
        el("span", {}, it.quantity !== 1 ? `${it.name} (${num(it.quantity, 3)}${it.is_weight ? " kg" : "×"})` : it.name),
        el("span", {}, money(it.amount, 2), it.discount ? el("span", { class: "disc" }, ` −${money(it.discount, 2)}`) : ""))));
      if (!items.length) list.append(el("li", { class: "muted" }, "Nem sikerült tételeket kiolvasni."));
      if (r.mismatched || !items.length) {
        list.append(el("li", {}, el("a", { href: `/api/receipts/${encodeURIComponent(r.id)}/raw`, target: "_blank" }, "Nyers adat megnyitása")));
      }
      li.append(list);
    });
    li.append(btn);
    $("#receipt-list").append(li);
  }
}

// ---------- main ----------

async function loadAll() {
  const p = periodParams();
  const q = p ? `?${p}` : "";
  const [summary, monthly, heat, stores] = await Promise.all([
    api(`/api/summary${q}`), api(`/api/monthly${q}`), api(`/api/weekday-hour${q}`), api(`/api/stores${q}`),
  ]);
  if (summary.currency) state.currency = summary.currency;
  $("#k-spend").textContent = money(summary.spend);
  $("#k-count").textContent = `${num(summary.receipts)} db`;
  $("#k-avg").textContent = money(summary.avg_basket);
  $("#k-save").textContent = money(summary.savings);
  const note = $("#mismatch-note");
  note.hidden = !summary.mismatched;
  note.textContent = `⚠ ${summary.mismatched} blokk tételei nem adják ki pontosan a végösszeget, ezeknél a termékstatisztika pontatlan lehet.`;
  renderMonthly(monthly);
  renderHeatmap(heat);
  renderBarList($("#store-list"), stores, (r) => r.receipts, (r) => `${r.receipts}× · ${money(r.spend)}`, (r) => r.store || "Ismeretlen");
  await Promise.all([loadTop(), loadReceipts(true)]);
}

async function refreshStatus() {
  const s = await api("/api/status");
  const btn = $("#sync-btn");
  btn.classList.toggle("spinning", s.syncing);
  btn.disabled = s.syncing;
  let text = s.last_sync ? `Frissítve: ${fmtDate(s.last_sync)} · ${s.receipts} blokk` : `${s.receipts} blokk`;
  if (s.syncing) text = "Letöltés folyamatban…";
  else if (s.last_sync_error) text += ` · Hiba: ${s.last_sync_error.slice(0, 120)}`;
  $("#sync-status").textContent = text;
  const empty = $("#empty");
  empty.hidden = s.receipts > 0;
  $("#empty-text").textContent = !s.has_token
    ? "Állítsd be a LIDL_REFRESH_TOKEN-t a szerveren (lidl-stats-login), majd indítsd újra."
    : s.syncing ? "Az első letöltés folyamatban, ez a blokkok számától függően pár percig is tarthat."
      : "Koppints a frissítés gombra a blokkok letöltéséhez.";
  return s;
}

async function pollSync() {
  const s = await refreshStatus();
  if (s.syncing) setTimeout(pollSync, 3000);
  else loadAll();
}

$("#sync-btn").addEventListener("click", async () => {
  await api("/api/sync", { method: "POST" });
  pollSync();
});

$("#period").addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  state.period = b.dataset.period;
  storage("period", state.period);
  document.querySelectorAll("#period button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
  loadAll();
});

$("#top-by").addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  state.topBy = b.dataset.by;
  document.querySelectorAll("#top-by button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
  loadTop();
});

$("#more-receipts").addEventListener("click", () => loadReceipts(false));

matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => loadAll());

(async function init() {
  const saved = storage("period");
  if (saved) {
    state.period = saved;
    document.querySelectorAll("#period button").forEach((x) => x.setAttribute("aria-pressed", String(x.dataset.period === saved)));
  }
  const s = await refreshStatus();
  if (s.syncing) pollSync();
  await loadAll();
})();
