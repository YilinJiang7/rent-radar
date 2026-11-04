/* Rent Radar front end: vanilla JS + Leaflet, talks to the FastAPI backend. */
"use strict";

const state = { meta: null, weights: {}, campus: "mit", listings: [], markers: new Map(), selected: null };
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const money = (n) => (n == null ? "–" : "$" + Number(n).toLocaleString("en-US"));
const color = (s) => (s == null ? "var(--none)" : s >= 70 ? "var(--good)" : s >= 50 ? "var(--mid)" : "var(--bad)");
const hex = (s) => (s == null ? "#8C939A" : s >= 70 ? "#2F7D5B" : s >= 50 ? "#C99A2E" : "#A8432F");

const EXAMPLES = [
  "budget 2500, class at MIT, hate noise, bike home at night",
  "2 bed in Allston under 3800 near Harvard SEAS, worried about landlord scams",
  "studio near Harvard Yard, no heat or rodent problems please",
];

const map = L.map("map", { zoomControl: true }).setView([42.360, -71.115], 13);
L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
  maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>',
}).addTo(map);
const layer = L.layerGroup().addTo(map);
const campusLayer = L.layerGroup().addTo(map);

const legend = L.control({ position: "bottomleft" });
legend.onAdd = () => {
  const d = L.DomUtil.create("div", "legend");
  d.innerHTML = '<b>Score</b><br><i style="background:#2F7D5B"></i>70+ <i style="background:#C99A2E"></i>50–69 <i style="background:#A8432F"></i>&lt;50<br><span class="muted">faded = on market &gt;180 days</span>';
  return d;
};
legend.addTo(map);

async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error((await r.text()) || r.statusText);
  return r.json();
}

function weightsParam() {
  return encodeURIComponent(JSON.stringify(state.weights));
}

function renderWeights() {
  const box = $("weights");
  box.innerHTML = "";
  for (const [k, f] of Object.entries(state.meta.factors)) {
    const row = document.createElement("div");
    row.className = "w";
    row.innerHTML = `<span title="${esc(f.how)}">${esc(f.label)}</span>
      <input type="range" min="0" max="5" step="1" value="${state.weights[k]}" data-k="${k}">
      <b>${state.weights[k]}</b>`;
    box.appendChild(row);
  }
  box.querySelectorAll("input").forEach((inp) =>
    inp.addEventListener("input", (e) => {
      state.weights[e.target.dataset.k] = Number(e.target.value);
      e.target.nextElementSibling.textContent = e.target.value;
      debounceLoad();
    })
  );
}

let t;
function debounceLoad() { clearTimeout(t); t = setTimeout(loadListings, 250); }

async function loadListings() {
  const p = new URLSearchParams({ campus: state.campus, include_stale: !$("hideStale").checked });
  if ($("maxPrice").value) p.set("max_price", $("maxPrice").value);
  if ($("minBeds").value) p.set("min_beds", $("minBeds").value);
  const data = await api(`/api/listings?${p}&weights=${weightsParam()}`);
  state.listings = data.listings;
  drawMarkers();
  renderList();
}

function drawMarkers(highlight = []) {
  layer.clearLayers();
  state.markers.clear();
  const hi = new Set(highlight);
  for (const l of state.listings) {
    const m = L.circleMarker([l.lat, l.lon], {
      radius: hi.has(l.id) ? 10 : 6, weight: hi.has(l.id) ? 3 : 1, color: hi.has(l.id) ? "#1B2A3A" : "#fff",
      fillColor: hex(l.score), fillOpacity: l.stale ? 0.35 : 0.9,
    }).bindTooltip(`${esc(l.address)}<br>${money(l.price)} · ${l.bedrooms ?? "?"} bd · score ${l.score ?? "–"}`);
    m.on("click", () => openDetail(l.id));
    m.addTo(layer);
    state.markers.set(l.id, m);
  }
}

function renderList() {
  $("count").textContent = `(${state.listings.length} shown)`;
  $("list").innerHTML = state.listings.slice(0, 12).map((l) =>
    `<li data-id="${esc(l.id)}"><span class="pill" style="background:${color(l.score)}">${l.score ?? "–"}</span>
     ${esc(l.address.split(",")[0])} <span class="muted">${money(l.price)} · ${l.bedrooms ?? "?"} bd · ${esc(l.area)}</span></li>`).join("");
  $("list").querySelectorAll("li").forEach((li) => li.addEventListener("click", () => openDetail(li.dataset.id)));
}

function drawCampuses() {
  campusLayer.clearLayers();
  for (const [k, c] of Object.entries(state.meta.campuses)) {
    const icon = L.divIcon({ className: "campus" + (k === state.campus ? " on" : ""), html: `<span>${esc(k.toUpperCase())}</span>`, iconSize: null });
    L.marker([c.lat, c.lon], { icon, zIndexOffset: 1000 }).bindTooltip(c.name).addTo(campusLayer);
  }
}

/* ---------- detail card ---------- */
function bar(score) {
  return `<div class="bar"><i style="width:${score ?? 0}%;background:${color(score)}"></i></div>`;
}

function kv(pairs) {
  return `<div class="kv">${pairs.map(([k, v]) => `<div>${esc(k)}</div><div>${v}</div>`).join("")}</div>`;
}

async function openDetail(id) {
  state.selected = id;
  const p = new URLSearchParams({ campus: state.campus });
  if ($("maxPrice").value) p.set("budget", $("maxPrice").value);
  const e = await api(`/api/listings/${encodeURIComponent(id)}?${p}&weights=${weightsParam()}`);
  const m = state.markers.get(id);
  if (m) map.panTo(m.getLatLng());
  const b = e.building || {}, o = e.owner || {}, s = e.street || {}, c = e.commute || {}, tr = e.transit || {}, n = e.noise || {};
  let h = `<h3>${esc(e.address)}</h3>
    <div class="muted">${esc(e.area)} · ${esc(e.property_type || "")} · listed ${esc(e.listed_date)} (${e.days_on_market ?? "?"} days on market)</div>
    <h4>Listing</h4>${kv([["Rent", money(e.price) + "/mo"], ["Bedrooms / baths", `${e.bedrooms ?? "?"} / ${e.bathrooms ?? "?"}`], ["Size", e.sqft ? e.sqft + " sq ft" : "–"]])}
    ${e.stale ? `<div class="flag">On market ${e.days_on_market} days — may be stale or already rented. Confirm it is available before visiting.</div>` : ""}
    <h4>Score ${e.score.total ?? "–"} / 100 <span class="muted">(uses ${e.score.weight_coverage_pct}% of weights)</span></h4>`;
  for (const f of e.score.breakdown) {
    h += `<div class="factor" title="${esc(state.meta.factors[f.factor].how)}"><span>${esc(f.label)} <span class="muted">×${f.weight}</span></span>${bar(f.score)}<span>${f.missing ? '<span class="muted">no data</span>' : f.score}</span></div>`;
  }
  h += `<h4>Building record (RentSmart)</h4>`;
  if (!b.available) h += `<div class="muted">${esc(b.reason)}</div>`;
  else {
    h += kv([["Records, last " + b.window_years + " yrs", b.records_window], ["Records, all years", b.records_total], ["Match", esc(b.match_type)]]);
    const sig = Object.entries(b.by_signal || {});
    if (sig.length) h += `<div class="flag">${sig.map(([k, v]) => `${esc(k.replace(/_/g, " "))} ×${v}`).join(" · ")}</div>`;
    else h += `<div class="ok">No complaints or violations matched in the last ${b.window_years} years.</div>`;
  }
  if ((e.records || []).length) {
    h += e.records.slice(0, 15).map((r) => `<div class="rec" id="rec-${esc(r.record_id)}"><b>${esc(r.date)}</b> · ${esc(r.violation_type)} — ${esc(r.description)} <span class="muted">[${esc(r.signal.replace(/_/g, " "))}${r.signal_source === "llm" ? ", AI label" : ""} · ${esc(r.match_type)} · R:${esc(r.record_id)}]</span></div>`).join("");
  }
  h += `<h4>Owner of record</h4>`;
  if (!o.available) h += `<div class="muted">${esc(o.reason)}</div>`;
  else {
    h += kv([["Owner", esc(o.owner)], ["Owner-occupied", o.owner_occupied == null ? "unknown" : o.owner_occupied ? "yes" : "no"],
      ["Mailing state", esc(o.mail_state || "–")], ["Owner's properties (Boston)", o.portfolio_properties ?? "–"],
      ["Serious records across them (3 yrs)", o.portfolio_serious_records_window]]);
    if (o.is_entity) h += `<div class="muted">Owned by a company/trust — the person you talk to should be able to show they manage it.</div>`;
  }
  const lc = (o.listing_contact || {});
  h += `<div class="flag">Before paying anything: ask the contact${lc.agent || lc.office ? ` (${esc([lc.agent, lc.office].filter(Boolean).join(", "))})` : ""} to show they own or manage this address, and never wire a deposit. In Massachusetts a landlord may collect at most first month, last month, a security deposit and a lock fee up front (M.G.L. c.186 §15B).</div>`;
  h += `<h4>Commute to ${esc(c.campus || "")}</h4>${kv([["Bike (estimate)", `~${c.bike_min} min`], ["Walk (estimate)", `~${c.walk_min} min`],
    ["Bike crashes along the way (2021–25)", c.corridor_bike_crashes ?? "–"], ["…of those after dark", c.corridor_bike_crashes_dark ?? "–"]])}`;
  h += `<h4>Transit</h4>` + (tr.available ? kv([["Nearest station", tr.station ? `${esc(tr.station)} <span class="muted">${esc(tr.lines || "")}</span>` : "none within 1.6 km"],
    ["Walk to station", tr.station ? `~${tr.station_walk_min} min` : "–"], ["Bus stops within 400 m", tr.bus_stops_400m]]) : `<div class="muted">${esc(tr.reason)}</div>`);
  h += `<h4>Street safety (MassDOT crashes within ${s.radius_m || 150} m)</h4>` + (s.available ? kv([["All crashes", s.crashes], ["Injury crashes", s.injury_crashes],
    ["Pedestrian / bike crashes", s.ped_bike_crashes], ["After dark", s.dark_crashes], ["Years", esc(s.years || "–")]]) : `<div class="muted">${esc(s.reason)}</div>`);
  h += `<h4>Traffic noise proxy</h4>` + (n.available ? kv([["Busiest road within 100 m", esc(n.busiest_road || "none recorded")], ["Traffic (AADT, vehicles/day)", n.max_aadt_100m ? Number(n.max_aadt_100m).toLocaleString() : "–"]]) : "<div class='muted'>not available</div>");
  h += `<p class="muted" style="margin-top:16px">Rent Radar never uses demographic data. "Safety" here means crash and building records only.</p>`;
  $("detailBody").innerHTML = h;
  $("detail").classList.remove("hidden");
}

/* ---------- agent ---------- */
function mdToHtml(md) {
  let s = esc(md);
  s = s.replace(/\[L:([^\]]+)\]/g, (_, id) => `<span class="cite" data-l="${id}">[listing]</span>`);
  s = s.replace(/\[R:([^\]]+)\]/g, (_, id) => `<span class="cite" data-r="${id}">[record ${id}]</span>`);
  s = s.replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/(^|\s)_(.+?)_(?=\s|$)/g, "$1<i>$2</i>");
  const lines = s.split("\n");
  let out = "", inOl = false, inUl = false;
  for (const ln of lines) {
    const ol = ln.match(/^\s*\d+\.\s+(.*)/), ul = ln.match(/^\s*[-*]\s+(.*)/);
    if (ol && !ln.startsWith("   ")) { if (inUl) { out += "</ul>"; inUl = false; } if (!inOl) { out += "<ol>"; inOl = true; } out += `<li>${ol[1]}`; continue; }
    if (ul) { if (!inUl) { out += "<ul>"; inUl = true; } out += `<li>${ul[1]}</li>`; continue; }
    if (inUl) { out += "</ul>"; inUl = false; }
    if (inOl && ln.trim() === "") { out += "</ol>"; inOl = false; }
    out += ln.trim() ? `<p>${ln}</p>` : "";
  }
  if (inUl) out += "</ul>";
  if (inOl) out += "</ol>";
  return out;
}

async function ask() {
  const q = $("q").value.trim();
  if (!q) return;
  $("ask").disabled = true;
  $("answer").classList.remove("hidden");
  $("answer").innerHTML = "<span class='muted'>Thinking…</span>";
  try {
    const r = await api("/api/agent", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: q, campus: state.campus }) });
    const g = r.grounding || {};
    $("answer").innerHTML = mdToHtml(r.answer) +
      `<div class="mode">${r.mode === "llm" ? "AI agent (" + esc(r.model) + ")" : r.mode === "guardrail" ? "Fair Housing guardrail" : "offline mode (no API key)"}
       · ${r.seconds}s · grounding: ${g.ok ? "all " + g.numbers_checked + " numbers found in tool results" : `<span class="warn">unverified numbers ${esc((g.ungrounded || []).join(", "))}</span>`}
       ${r.fallback_reason ? `<br><span class="warn">LLM failed, used offline mode: ${esc(r.fallback_reason)}</span>` : ""}</div>`;
    $("answer").querySelectorAll(".cite[data-l]").forEach((el) => el.addEventListener("click", () => openDetail(el.dataset.l)));
    $("answer").querySelectorAll(".cite[data-r]").forEach((el) => el.addEventListener("click", async () => {
      const rec = await api(`/api/records/${encodeURIComponent(el.dataset.r)}`);
      el.title = `${rec.date} ${rec.violation_type}: ${rec.description} (${rec.address})`;
      alertBox(el.title);
    }));
    if (r.plan && r.plan.weights_used) {
      state.weights = { ...state.weights, ...r.plan.weights_used };
      renderWeights();
    }
    if (r.plan && r.plan.args && r.plan.args.campus && r.plan.args.campus !== state.campus) {
      state.campus = r.plan.args.campus; $("campus").value = state.campus; drawCampuses();
    }
    await loadListings();
    const ids = (r.ranked || []).map((x) => x.id);
    drawMarkers(ids);
    if (ids.length) map.fitBounds(L.latLngBounds(ids.map((id) => state.markers.get(id)).filter(Boolean).map((m) => m.getLatLng())).pad(0.4));
    $("trace").innerHTML = (r.tool_trace || []).map((t) => `<div class="rec"><b>${esc(t.tool)}</b>(${esc(JSON.stringify(t.args))}) → ${esc(t.result)}</div>`).join("");
    $("tracebox").classList.toggle("hidden", !(r.tool_trace || []).length);
  } catch (err) {
    $("answer").innerHTML = `<span class="warn">Error: ${esc(err.message)}</span>`;
  } finally {
    $("ask").disabled = false;
  }
}

function alertBox(text) {
  const d = document.createElement("div");
  d.className = "flag";
  d.textContent = text;
  $("answer").appendChild(d);
}

async function init() {
  state.meta = await api("/api/meta");
  state.weights = { ...state.meta.default_weights };
  $("campus").innerHTML = Object.entries(state.meta.campuses).map(([k, c]) => `<option value="${k}">${esc(c.name)}</option>`).join("");
  $("campus").value = state.campus;
  $("examples").innerHTML = EXAMPLES.map((x) => `<button type="button">${esc(x)}</button>`).join("");
  $("examples").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => { $("q").value = b.textContent; ask(); }));
  const b = state.meta.build || {};
  const src = b.sources || {};
  $("status").textContent = `${state.meta.listing_count} listings · data as of ${b.as_of || "?"}${b.fixtures ? " · SYNTHETIC FIXTURES" : ""} · ` +
    ["rentsmart", "assessment", "crashes", "stops"].map((k) => `${k} ${src[k] && src[k].rows ? "✓" : "✗"}`).join(" ") +
    ` · ${state.meta.llm ? "AI: " + state.meta.llm : "AI: offline mode"}`;
  renderWeights();
  drawCampuses();
  $("ask").addEventListener("click", ask);
  $("q").addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) ask(); });
  $("campus").addEventListener("change", (e) => { state.campus = e.target.value; drawCampuses(); loadListings(); });
  ["maxPrice", "minBeds"].forEach((id) => $(id).addEventListener("input", debounceLoad));
  $("hideStale").addEventListener("change", loadListings);
  $("resetW").addEventListener("click", () => { state.weights = { ...state.meta.default_weights }; renderWeights(); loadListings(); });
  $("close").addEventListener("click", () => $("detail").classList.add("hidden"));
  await loadListings();
}

init().catch((e) => { $("status").textContent = "Error: " + e.message; });
