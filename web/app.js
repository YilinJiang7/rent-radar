/* Rent Radar front end: vanilla JS + Leaflet over the FastAPI backend.
   Principle: conclusions first (score + 3 flags), details on demand. */
"use strict";

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const money = (n) => (n == null ? "–" : "$" + Number(n).toLocaleString("en-US"));
const beds = (b) => (b == null ? "? bd" : b === 0 ? "Studio" : `${b} bd`);
const street = (addr) => String(addr || "").split(",")[0];
const scoreColor = (s) => (s == null ? "#9AA1A8" : s >= 70 ? "#2F7D5B" : s >= 50 ? "#B9831F" : "#B3402B");

const state = {
  meta: null, weights: {}, campus: "mit", listings: [], byId: new Map(), markers: new Map(),
  agentIds: null, shown: 10, selected: null,
};

const EXAMPLES = [
  ["Quiet, MIT, under $2.5k", "budget 2500, class at MIT, hate noise, bike home at night"],
  ["2 bed Allston, safe landlord", "2 bed in Allston under 3800 near Harvard SEAS, worried about landlord scams, include old listings"],
  ["Studio near Harvard, no pests", "studio near Harvard Yard, no heat or rodent problems please"],
];
const CAMPUS_LABEL = { mit: "MIT", harvard: "Harvard Yard", seas: "SEAS" };

/* ---------- map ---------- */
const map = L.map("map", { zoomControl: true }).setView([42.360, -71.115], 13);
L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
  maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>',
}).addTo(map);
const pins = L.layerGroup().addTo(map);
const campusLayer = L.layerGroup().addTo(map);
const legend = L.control({ position: "bottomleft" });
legend.onAdd = () => {
  const d = L.DomUtil.create("div", "legend");
  d.innerHTML = '<i style="background:#2F7D5B"></i>70+ <i style="background:#B9831F"></i>50–69 <i style="background:#B3402B"></i>under 50 · faded = old listing';
  return d;
};
legend.addTo(map);

async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error((await r.text()) || r.statusText);
  return r.json();
}
const wParam = () => encodeURIComponent(JSON.stringify(state.weights));

function pinStyle(l, on) {
  return { radius: on ? 10 : 6, weight: on ? 3 : 1, color: on ? "#1B2A3A" : "#fff",
           fillColor: scoreColor(l.score), fillOpacity: l.stale ? 0.35 : 0.9 };
}

function drawPins() {
  pins.clearLayers();
  state.markers.clear();
  const hi = new Set(state.agentIds || []);
  for (const l of state.listings) {
    const m = L.circleMarker([l.lat, l.lon], pinStyle(l, hi.has(l.id)))
      .bindTooltip(`<b>${esc(street(l.address))}</b><br>${money(l.price)} · ${beds(l.bedrooms)} · score ${l.score ?? "–"}`);
    m.on("click", () => openDetail(l.id));
    m.addTo(pins);
    state.markers.set(l.id, m);
  }
}

function highlight(id, on) {
  const m = state.markers.get(id), l = state.byId.get(id);
  if (!m || !l) return;
  m.setStyle(pinStyle(l, on || (state.agentIds || []).includes(id)));
  if (on) m.bringToFront();
}

function drawCampuses() {
  campusLayer.clearLayers();
  for (const [k, c] of Object.entries(state.meta.campuses)) {
    const icon = L.divIcon({ className: "campus" + (k === state.campus ? " on" : ""), html: `<span>${esc(CAMPUS_LABEL[k] || k)}</span>`, iconSize: null });
    L.marker([c.lat, c.lon], { icon, zIndexOffset: 1000 }).bindTooltip(c.name).addTo(campusLayer);
  }
}

/* ---------- list ---------- */
async function loadListings() {
  const p = new URLSearchParams({ campus: state.campus, include_stale: !$("hideStale").checked });
  if ($("maxPrice").value) p.set("max_price", $("maxPrice").value);
  if ($("minBeds").value) p.set("min_beds", $("minBeds").value);
  const data = await api(`/api/listings?${p}&weights=${wParam()}`);
  state.listings = data.listings;
  state.byId = new Map(data.listings.map((l) => [l.id, l]));
  drawPins();
  renderCards();
}

function cardHTML(l) {
  const flags = (l.flags || []).map((f) => `<li class="${f.kind}">${esc(f.text)}</li>`).join("");
  return `<li class="card" data-id="${esc(l.id)}">
    <div class="badge" style="background:${scoreColor(l.score)}">${l.score == null ? "–" : Math.round(l.score)}</div>
    <div>
      <div class="street">${esc(street(l.address))}${l.stale ? '<span class="old">OLD LISTING</span>' : ""}</div>
      <div class="sub">${esc(l.area)} · ${money(l.price)} · ${beds(l.bedrooms)}</div>
      <ul class="flags">${flags}</ul>
    </div></li>`;
}

function renderCards() {
  let rows;
  if (state.agentIds) {
    rows = state.agentIds.map((id) => state.byId.get(id)).filter(Boolean);
    $("listTitle").innerHTML = `Agent’s picks <small>${rows.length}</small>`;
  } else {
    rows = state.listings;
    $("listTitle").innerHTML = `Best matches <small>${rows.length} listings</small>`;
  }
  const shown = state.agentIds ? rows : rows.slice(0, state.shown);
  $("cards").innerHTML = shown.map(cardHTML).join("") +
    (!state.agentIds && rows.length > shown.length ? `<li class="more"><button class="ghost small" id="moreBtn">Show more</button></li>` : "") +
    (state.agentIds ? `<li class="more"><button class="link" id="clearAgent">← Back to all listings</button></li>` : "");
  $("cards").querySelectorAll(".card").forEach((c) => {
    c.addEventListener("click", () => openDetail(c.dataset.id));
    c.addEventListener("mouseenter", () => highlight(c.dataset.id, true));
    c.addEventListener("mouseleave", () => highlight(c.dataset.id, false));
  });
  const more = $("moreBtn");
  if (more) more.addEventListener("click", () => { state.shown += 15; renderCards(); });
  const clear = $("clearAgent");
  if (clear) clear.addEventListener("click", clearAgent);
}

/* ---------- weights / filters ---------- */
function renderWeights() {
  $("weights").innerHTML = Object.entries(state.meta.factors).map(([k, f]) => `
    <div class="w" title="${esc(f.how)}"><span>${esc(f.label)}</span>
      <input type="range" min="0" max="5" step="1" value="${state.weights[k]}" data-k="${k}" aria-label="${esc(f.label)} weight">
      <b>${state.weights[k]}</b></div>`).join("");
  $("weights").querySelectorAll("input").forEach((inp) => inp.addEventListener("input", (e) => {
    state.weights[e.target.dataset.k] = Number(e.target.value);
    e.target.nextElementSibling.textContent = e.target.value;
    debounce(loadListings);
  }));
}
let timer;
function debounce(fn) { clearTimeout(timer); timer = setTimeout(fn, 250); }

function renderCampus() {
  $("campusSeg").innerHTML = '<span>Campus</span>' + Object.keys(state.meta.campuses).map((k) =>
    `<button role="radio" aria-checked="${k === state.campus}" data-k="${k}">${esc(CAMPUS_LABEL[k] || k)}</button>`).join("");
  $("campusSeg").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => setCampus(b.dataset.k)));
}
function setCampus(k) {
  if (k === state.campus) return;
  state.campus = k;
  renderCampus(); drawCampuses(); loadListings();
  if (state.selected) openDetail(state.selected);
}

/* ---------- detail ---------- */
const sec = (title, count, body, open = false) =>
  `<details class="sec"${open ? " open" : ""}><summary><span>${title}${count != null ? `<small>${count}</small>` : ""}</span></summary><div class="body">${body}</div></details>`;
const kv = (pairs) => `<div class="kv">${pairs.map(([k, v]) => `<div>${esc(k)}</div><div>${v}</div>`).join("")}</div>`;
const ICON = { bad: "!", good: "✓", info: "i" };

async function openDetail(id) {
  state.selected = id;
  const p = new URLSearchParams({ campus: state.campus });
  if ($("maxPrice").value) p.set("budget", $("maxPrice").value);
  const e = await api(`/api/listings/${encodeURIComponent(id)}?${p}&weights=${wParam()}`);
  const m = state.markers.get(id);
  if (m) map.panTo(m.getLatLng());
  document.querySelectorAll(".card").forEach((c) => c.classList.toggle("on", c.dataset.id === id));

  const b = e.building || {}, o = e.owner || {}, s = e.street || {}, c = e.commute || {}, t = e.transit || {}, n = e.noise || {};
  const sc = e.score.total;
  const glance = (e.flags || []).filter((f) => f.topic !== "listing")
    .map((f) => `<li class="${f.kind}"><i>${ICON[f.kind]}</i>${esc(f.text)}</li>`).join("");

  let h = `<div class="dhead">
      <div><h3>${esc(street(e.address))}</h3><div class="sub">${esc(e.area)} · ${esc(e.property_type || "")}${e.address.includes(",") ? " · " + esc(e.address.split(",").slice(1, 2).join("").trim()) : ""}</div>
        <div class="price">${money(e.price)}<span> /mo · ${beds(e.bedrooms)} · ${e.bathrooms ?? "?"} ba${e.sqft ? ` · ${e.sqft} sq ft` : ""}</span></div></div>
      <div class="ring" style="background:conic-gradient(${scoreColor(sc)} ${(sc || 0) * 3.6}deg, #E4DFD4 0)" title="Score based on ${e.score.weight_coverage_pct}% of the weights">
        <div><span>${sc == null ? "–" : Math.round(sc)}<small>score</small></span></div></div>
    </div>`;
  if (e.stale) h += `<div class="banner">Listed ${e.days_on_market} days ago. It may already be rented, so confirm before visiting.</div>`;
  h += `<ul class="glance">${glance}</ul>`;

  // why this score
  const factors = e.score.breakdown.map((f) => `<div class="factor" title="${esc(state.meta.factors[f.factor].how)}">
      <span>${esc(f.label)}</span><div class="bar"><i style="width:${f.score ?? 0}%;background:${scoreColor(f.score)}"></i></div>
      <span class="${f.missing ? "muted" : ""}">${f.missing ? "n/a" : Math.round(f.score)}</span></div>`).join("");
  h += sec("Why this score", null, factors + `<div class="note">Based on ${e.score.weight_coverage_pct}% of your weights; “n/a” factors have no data here and are left out. Hover a row for its formula.</div>`);

  // building
  if (!b.available) h += sec("Building record", null, `<div class="note">${esc(b.reason)}</div>`);
  else {
    const recs = (e.records || []).slice(0, 12).map((r) => `<div class="rec"><time>${esc((r.date || "").slice(0, 7))}</time>
        <div><div class="what${r.serious ? " serious" : ""}">${esc(r.label)}</div><div class="desc">${esc(r.description)}</div></div></div>`).join("");
    h += sec("Building record", `${b.records_window} in ${b.window_years} yrs`,
      (recs || `<div class="note">No complaints or violations found for this address.</div>`) +
      `<div class="note">Source: RentSmart Boston (311 + inspections). Matched by ${esc(b.match_type)}.</div>`);
  }

  // owner
  let ob;
  if (!o.available) ob = `<div class="note">${esc(o.reason)}</div>`;
  else ob = kv([["Owner of record", esc(o.owner)],
    ["Lives in the building", o.owner_occupied == null ? "unknown" : o.owner_occupied ? "yes" : "no"],
    ["Boston properties", o.portfolio_properties ?? "–"],
    ["Serious issues across them (3 yrs)", o.portfolio_serious_records_window],
    ["Mailing state", esc(o.mail_state || "–")]]);
  const lc = o.listing_contact || {};
  ob += `<div class="tip"><b>Before you pay anything:</b> ask${lc.agent || lc.office ? ` ${esc([lc.agent, lc.office].filter(Boolean).join(", "))}` : " the contact"} to show they own or manage this address. Never wire a deposit. In MA a landlord can collect at most first and last month, a security deposit and a lock fee (M.G.L. c.186 §15B).</div>`;
  h += sec("Owner", o.available ? (o.is_entity ? "company / trust" : "individual") : null, ob);

  // getting there
  h += sec(`Getting to ${esc(CAMPUS_LABEL[state.campus])}`, c.bike_min != null ? `~${c.bike_min} min bike` : null,
    kv([["Bike (estimate)", `~${c.bike_min} min`], ["Walk (estimate)", `~${c.walk_min} min`],
        ["Nearest T", t.station ? `${esc(t.station)} · ${t.station_walk_min} min` : "none nearby"],
        ["Lines", esc(t.lines || "–")], ["Bus stops within 400 m", t.bus_stops_400m ?? "–"]]) +
    `<div class="note">Straight-line distance × 1.3; real trip times come in the final version.</div>`);

  // street
  h += sec("Street & noise", s.available ? `${s.injury_crashes} injury crash${s.injury_crashes === 1 ? "" : "es"}` : null,
    s.available ? kv([[`Crashes within ${s.radius_m} m (${s.years || "2021–25"})`, s.crashes], ["…with injuries", s.injury_crashes],
      ["…involving walkers or bikes", s.ped_bike_crashes], ["…after dark", s.dark_crashes],
      ["Bike crashes on the way to campus", c.corridor_bike_crashes ?? "–"],
      ["Busiest road within 100 m", n.busiest_road ? `${esc(n.busiest_road)} (${Number(n.max_aadt_100m).toLocaleString()} cars/day)` : "none recorded"]])
      + `<div class="note">MassDOT crash records. “Safety” here never means who lives nearby.</div>` : `<div class="note">${esc(s.reason)}</div>`);

  $("detailBody").innerHTML = h;
  $("detail").classList.remove("hidden");
  $("detail").scrollTop = 0;
}

/* ---------- agent ---------- */
function mdToHtml(md) {
  let s = esc(md);
  s = s.replace(/\[L:([^\]]+)\]/g, (_, id) => `<a href="#" class="cite" data-l="${id}">open</a>`);
  s = s.replace(/\s*\[R:[^\]]+\]/g, "");
  s = s.replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/(^|\s)_(.+?)_(?=\s|$)/g, "$1<i>$2</i>");
  let out = "", list = null;
  for (const ln of s.split("\n")) {
    const ol = ln.match(/^\d+\.\s+(.*)/), ul = ln.match(/^\s*[-*]\s+(.*)/);
    if (ol) { if (list !== "ol") { if (list) out += `</${list}>`; out += "<ol>"; list = "ol"; } out += `<li>${ol[1]}</li>`; continue; }
    if (ul) { if (list !== "ul") { if (list) out += `</${list}>`; out += "<ul>"; list = "ul"; } out += `<li>${ul[1]}</li>`; continue; }
    if (list) { out += `</${list}>`; list = null; }
    if (ln.trim()) out += `<p>${ln}</p>`;
  }
  if (list) out += `</${list}>`;
  return out;
}

function understoodTags(r) {
  const tags = [];
  const f = (r.plan && r.plan.filters) || {};
  const areaName = Object.fromEntries((state.meta.areas || []).map((a) => [a.zip, a.area]));
  tags.push(`<span class="tag">${esc(CAMPUS_LABEL[(r.plan && r.plan.args && r.plan.args.campus) || state.campus] || "")}</span>`);
  if (f.max_price) tags.push(`<span class="tag">≤ ${money(f.max_price)}</span>`);
  if (f.min_beds != null) tags.push(`<span class="tag">${f.min_beds === 0 && f.max_beds === 0 ? "Studio" : f.min_beds + (f.max_beds == null ? "+" : "") + " bd"}</span>`);
  (f.areas || []).forEach((z) => tags.push(`<span class="tag">${esc(areaName[z] || z)}</span>`));
  if (f.max_bike_min) tags.push(`<span class="tag">bike ≤ ${f.max_bike_min} min</span>`);
  if (f.include_stale) tags.push(`<span class="tag">incl. old listings</span>`);
  const used = (r.plan && r.plan.weights_used) || {};
  for (const [k, v] of Object.entries(used)) {
    if (v > (state.meta.default_weights[k] ?? 0)) tags.push(`<span class="tag up">↑ ${esc(state.meta.factors[k].label)}</span>`);
  }
  return tags.join("");
}

async function ask(ev) {
  if (ev) ev.preventDefault();
  const q = $("q").value.trim();
  if (!q) return;
  $("askBtn").disabled = true;
  const box = $("understood");
  box.classList.remove("hidden");
  box.innerHTML = '<span class="lbl">Thinking…</span>';
  try {
    const r = await api("/api/agent", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: q, campus: state.campus }) });
    if (r.mode === "guardrail") {
      box.innerHTML = `<div class="lbl">Can’t do that one</div><div class="refusal">${esc(r.answer)}</div>`;
      if (state.agentIds) { state.agentIds = null; renderCards(); drawPins(); }
      return;
    }
    if (r.plan && r.plan.weights_used) { state.weights = { ...state.weights, ...r.plan.weights_used }; renderWeights(); }
    const c = r.plan && r.plan.args && r.plan.args.campus;
    if (c && c !== state.campus && state.meta.campuses[c]) { state.campus = c; renderCampus(); drawCampuses(); }
    const f = (r.plan && r.plan.filters) || {};
    $("maxPrice").value = f.max_price || "";
    $("minBeds").value = f.min_beds ?? "";
    $("hideStale").checked = !f.include_stale;
    const g = r.grounding || {};
    const mode = r.mode === "llm" ? `AI agent (${esc(r.model)})` : "offline mode";
    box.innerHTML = `<div class="lbl">I read this as</div><div class="tags">${understoodTags(r)}</div>
      <div class="verified${g.ok ? "" : " warn"}">${g.ok ? `✓ All ${g.numbers_checked} numbers checked against the records` : `⚠ Unverified numbers: ${esc((g.ungrounded || []).join(", "))}`} · ${mode}${r.fallback_reason ? " (AI unavailable)" : ""}</div>
      <details><summary>Read the agent’s explanation</summary><div class="explain">${mdToHtml(r.answer)}</div></details>`;
    box.querySelectorAll(".cite").forEach((a) => a.addEventListener("click", (e) => { e.preventDefault(); openDetail(a.dataset.l); }));
    state.agentIds = (r.ranked || []).map((x) => x.id);
    await loadListings();
    const pts = state.agentIds.map((id) => state.markers.get(id)).filter(Boolean).map((m) => m.getLatLng());
    if (pts.length) map.fitBounds(L.latLngBounds(pts).pad(0.5), { maxZoom: 15 });
    if (!state.agentIds.length) $("cards").insertAdjacentHTML("afterbegin", `<li class="note">No listing matches all of that. Try a higher budget or fewer bedrooms.</li>`);
  } catch (err) {
    box.innerHTML = `<div class="verified warn">Error: ${esc(err.message)}</div>`;
  } finally {
    $("askBtn").disabled = false;
  }
}

function clearAgent() {
  state.agentIds = null;
  $("understood").classList.add("hidden");
  state.weights = { ...state.meta.default_weights };
  renderWeights();
  loadListings();
}

/* ---------- about ---------- */
function renderAbout() {
  const b = state.meta.build || {}, src = b.sources || {};
  const row = (name, key, note) => {
    const s = src[key] || {};
    return `<tr><td>${name}</td><td>${s.rows ? Number(s.rows).toLocaleString() + " " + note : "not loaded"}</td></tr>`;
  };
  $("aboutBody").innerHTML = `<h3>About the data</h3>
    <table>
      ${row("Rental listings (RentCast)", "listings", "listings")}
      ${row("Complaints & violations (RentSmart Boston)", "rentsmart", "records")}
      ${row("Owners of record (Boston assessment)", "assessment", "parcels")}
      ${row("Crashes 2021–25 (MassDOT)", "crashes", "crashes")}
      ${row("Transit stops (MBTA)", "stops", "stops")}
    </table>
    <p>Data as of ${esc(b.as_of || "?")}${b.fixtures ? " · SYNTHETIC TEST DATA" : ""} · AI: ${esc(state.meta.llm || "offline mode")}</p>
    <h4>How the score works</h4>
    <p>A weighted average of the factors under “Adjust”. Factors with no data (e.g. city records for Cambridge) are left out, never guessed.</p>
    <h4>Fair housing</h4>
    <p>Rent Radar never uses data about who lives somewhere. “Safety” means crash and building records only.</p>`;
}

/* ---------- init ---------- */
async function init() {
  state.meta = await api("/api/meta");
  state.weights = { ...state.meta.default_weights };
  renderCampus(); drawCampuses(); renderWeights(); renderAbout();
  $("examples").innerHTML = EXAMPLES.map(([label, q]) => `<button type="button" data-q="${esc(q)}">${esc(label)}</button>`).join("");
  $("examples").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => { $("q").value = b.dataset.q; ask(); }));
  $("askForm").addEventListener("submit", ask);
  $("q").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) ask(e); });
  $("adjustBtn").addEventListener("click", () => {
    const open = $("adjust").classList.toggle("hidden") === false;
    $("adjustBtn").setAttribute("aria-expanded", open);
  });
  ["maxPrice", "minBeds"].forEach((id) => $(id).addEventListener("input", () => debounce(loadListings)));
  $("hideStale").addEventListener("change", loadListings);
  $("resetW").addEventListener("click", () => { state.weights = { ...state.meta.default_weights }; renderWeights(); loadListings(); });
  $("closeDetail").addEventListener("click", () => { $("detail").classList.add("hidden"); state.selected = null;
    document.querySelectorAll(".card.on").forEach((c) => c.classList.remove("on")); });
  $("aboutBtn").addEventListener("click", () => $("about").showModal());
  $("closeAbout").addEventListener("click", () => $("about").close());
  await loadListings();
}
init().catch((e) => { $("cards").innerHTML = `<li class="verified warn">Error: ${esc(e.message)}</li>`; });
