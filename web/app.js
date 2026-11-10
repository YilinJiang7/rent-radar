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
  areas: [], sort: "score", plan: null, edited: false, ownerOcc: "plus",
};
const OWNER_LABEL = { plus: "owner in building = good", neutral: "owner in building = neutral", minus: "rather not share with owner" };

const EXAMPLES = [
  ["Quiet, MIT, under $2.5k", "budget 2500, class at MIT, hate noise, bike home at night"],
  ["2 bed Allston, landlord check", "2 bed in Allston under 3800 near Harvard SEAS, worried about landlord scams"],
  ["Studio near Harvard, no pests", "studio near Harvard Yard, no heat or rodent problems please"],
];
const CAMPUS_LABEL = { mit: "MIT", harvard: "Harvard Yard", seas: "SEAS" };

/* ---------- map ---------- */
const map = L.map("map", { zoomControl: true }).setView([42.360, -71.115], 13);
// OpenStreetMap standard tiles: free, no API key (CARTO basemaps now require one).
// Pins carry the colour, so the base map is dimmed a little to keep them readable.
L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19, className: "basemap",
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
}).addTo(map);
const pins = L.layerGroup().addTo(map);
const campusLayer = L.layerGroup().addTo(map);
const legend = L.control({ position: "bottomleft" });
legend.onAdd = () => {
  const d = L.DomUtil.create("div", "legend");
  d.innerHTML = '<i style="background:#2F7D5B"></i>70+ <i style="background:#B9831F"></i>50–69 <i style="background:#B3402B"></i>under 50 · faded = listed 91–180 days ago';
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
      .bindTooltip(`<b>${esc(street(l.address))}</b><br>${money(l.price)} · ${beds(l.bedrooms)} · score ${l.score ?? "–"}${l.city === "Cambridge" ? "<br><i>listing only, no city records</i>" : ""}`);
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
  const p = new URLSearchParams({ campus: state.campus, include_stale: $("showOlder").checked,
                                   cambridge: $("showCambridge").checked });
  if ($("maxPrice").value) p.set("max_price", $("maxPrice").value);
  if ($("minBeds").value) p.set("min_beds", $("minBeds").value);
  if (state.areas.length) p.set("area", state.areas.join(","));
  p.set("owner_occ", state.ownerOcc);
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
      <div class="street">${esc(street(l.address))}${l.units > 1 ? `<span class="units">+${l.units - 1} more unit${l.units > 2 ? "s" : ""}</span>` : ""}${l.stale ? '<span class="old">OLDER</span>' : ""}${l.city === "Cambridge" ? '<span class="old">LISTING ONLY</span>' : ""}</div>
      <div class="sub">${esc(l.area)} · ${money(l.price)} · ${beds(l.bedrooms)}</div>
      <ul class="flags">${flags}</ul>
    </div></li>`;
}

const bkey = (l) => `${street(l.address).toLowerCase().replace(/[^a-z0-9]/g, "")}|${l.area}`;

/* one card per building: the best-scoring unit, plus a count of the others */
function groupByBuilding(rows) {
  const seen = new Map();
  for (const l of rows) {
    const k = bkey(l);
    if (seen.has(k)) seen.get(k).units += 1;
    else seen.set(k, { ...l, units: 1 });
  }
  return [...seen.values()];
}

const SORTS = {
  score: (a, b) => (b.score ?? -1) - (a.score ?? -1),
  price: (a, b) => a.price - b.price,
  bike: (a, b) => (a.bike_min ?? 999) - (b.bike_min ?? 999),
  building: (a, b) => ((b.factors || {}).building ?? -1) - ((a.factors || {}).building ?? -1),
  fresh: (a, b) => (a.days_on_market ?? 9999) - (b.days_on_market ?? 9999),
};

function renderCards() {
  let rows;
  if (state.agentIds) {
    rows = groupByBuilding(state.agentIds.map((id) => state.byId.get(id)).filter(Boolean));
    $("listTitle").innerHTML = `Agent’s picks <small>${rows.length}</small>`;
  } else {
    rows = groupByBuilding([...state.listings].sort(SORTS[state.sort] || SORTS.score));
    $("listTitle").innerHTML = `${state.edited ? "Your edits" : "Best matches"} <small>${state.listings.length} listings in ${rows.length} buildings</small>`;
  }
  if (state.agentIds && state.sort !== "score") rows.sort(SORTS[state.sort]);
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
    if (state.plan) renderUnderstood();
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
  const p = new URLSearchParams({ campus: state.campus, owner_occ: state.ownerOcc });
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
  if (e.stale) h += `<div class="banner">Older backup listing: listed ${e.days_on_market} days ago. It may already be rented, so confirm it is available before visiting.</div>`;
  h += `<ul class="glance">${glance}</ul>`;

  // why this score
  const factors = e.score.breakdown.map((f) => `<div class="factor" title="${esc(state.meta.factors[f.factor].how)}">
      <span>${esc(f.label)}</span><div class="bar"><i style="width:${f.score ?? 0}%;background:${scoreColor(f.score)}"></i></div>
      <span class="${f.missing ? "muted" : f.neutral ? "neutral" : ""}">${f.missing ? "n/a" : f.neutral ? `${Math.round(f.score)} unknown` : Math.round(f.score)}</span></div>`).join("");
  h += sec("Why this score", null, factors + `<div class="note">Based on ${e.score.weight_coverage_pct}% of your weights. “unknown” = the city has no entry for this address, so it gets the average of all listings (building ${Math.round((e.score.neutral_values || {}).building ?? 50)}, owner ${Math.round((e.score.neutral_values || {}).landlord ?? 50)}): missing data is never a bonus or a penalty. “n/a” = factor not available here and left out. Hover a row for its formula.</div>`);

  // building
  if (!b.available) h += sec("Building record", null, `<div class="note">${esc(b.reason)}</div>`);
  else {
    const recs = (e.records || []).slice(0, 12).map((r) => `<div class="rec"><time>${esc((r.date || "").slice(0, 7))}</time>
        <div><div class="what${r.serious ? " serious" : ""}">${esc(r.label)}</div><div class="desc">${esc(r.description)}</div></div></div>`).join("");
    const since = (b.window_start || "").slice(0, 7), thru = (b.data_through || "").slice(0, 10);
    const empty = b.evidence === "unmatched"
      ? `<div class="note">We could not match this address to Boston’s property or complaint data, so there is <b>no evidence either way</b>.</div>`
      : `<div class="note">No complaints or violations on record for this address. That is <b>limited evidence, not proof</b>: problems are often never reported.</div>`;
    h += sec("Building record", b.evidence === "unmatched" ? "not matched" : `${b.records_window} since ${since}`,
      (recs || empty) +
      `<div class="note">RentSmart Boston (311 + inspections), records through ${esc(thru)}. Counts use the last ${b.window_years} years (since ${esc(since)}).${b.match_type && b.match_type !== "none" ? " Matched by " + esc(b.match_type) + "." : ""}</div>`);
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
  h += sec("Crashes & traffic", s.available ? `${s.injury_crashes} injury crash${s.injury_crashes === 1 ? "" : "es"}` : null,
    s.available ? kv([[`Crashes within ${s.radius_m} m (${s.years || "2021–25"})`, s.crashes], ["…with injuries", s.injury_crashes],
      ["…involving walkers or bikes", s.ped_bike_crashes], ["…after dark", s.dark_crashes],
      ["Bike crashes on the way to campus", c.corridor_bike_crashes ?? "–"],
      ["Busiest road within 100 m", n.busiest_road ? `${esc(n.busiest_road)} (${Number(n.max_aadt_100m).toLocaleString()} cars/day)` : "none recorded"]])
      + `<div class="note">MassDOT police-reported crashes, ${esc(s.years || "2021–2025")}, within ${s.radius_m} m of the address. They describe traffic on this street, not your personal safety, and never who lives nearby.</div>` : `<div class="note">${esc(s.reason)}</div>`);

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

/* "I read this as": the agent's reading of the request as chips you can edit.
   Filter chips remove with ×; priority chips toggle the weight between boosted (5) and default. */
function chip(label, data, cls = "", title = "", removable = true) {
  return `<span class="tag ${cls}" data-chip="${esc(data)}" title="${esc(title)}">${label}${removable ? '<span class="x">×</span>' : ""}</span>`;
}

function renderUnderstood() {
  const r = state.plan;
  if (!r) return;
  const f = r.filters || {};
  const areaName = Object.fromEntries((state.meta.areas || []).map((a) => [a.zip, a.area]));
  const tags = [];
  tags.push(chip(esc(CAMPUS_LABEL[state.campus] || ""), "campus", "fixed", "Change the campus in the top bar", false));
  if ($("maxPrice").value) tags.push(chip(`≤ ${money($("maxPrice").value)}`, "price", "", "Remove the budget limit"));
  if ($("minBeds").value !== "") {
    const mn = Number($("minBeds").value), mx = f.max_beds;
    tags.push(chip(mn === 0 && mx === 0 ? "Studio" : mx != null && mx === mn ? `${mn} bd` : `${mn}+ bd`, "beds", "", "Remove the bedroom filter"));
  }
  state.areas.forEach((z) => tags.push(chip(esc(areaName[z] || z), `area:${z}`, "", "Remove this neighborhood filter")));
  if ($("showOlder").checked) tags.push(chip("incl. older backups", "older", "", "Hide listings older than 90 days"));
  tags.push(chip($("showCambridge").checked ? "Boston + Cambridge (listing only)" : "Boston only", "cambridge", "", $("showCambridge").checked ? "Click to show Boston only" : "Click to include Cambridge", false));
  for (const [k, v] of Object.entries(state.weights)) {
    const d = state.meta.default_weights[k] ?? 0;
    if (v > d) tags.push(chip(`↑ ${esc(state.meta.factors[k].label)} <small>${v}</small>`, `weight:${k}`, "up", `Weight raised from ${d} to ${v}. Click to reset to ${d}.`));
  }
  if (state.ownerOcc !== "plus") tags.push(chip(esc(OWNER_LABEL[state.ownerOcc]), "owner", "", "Click to treat an owner in the building as a good sign again"));
  $("chips").innerHTML = tags.join("");
  $("chips").querySelectorAll(".tag").forEach((el) => el.addEventListener("click", () => onChip(el.dataset.chip)));
}

async function onChip(kind) {
  if (kind === "campus") return;
  if (kind === "price") $("maxPrice").value = "";
  else if (kind === "beds") $("minBeds").value = "";
  else if (kind.startsWith("area:")) state.areas = state.areas.filter((z) => z !== kind.slice(5));
  else if (kind === "older") $("showOlder").checked = false;
  else if (kind === "cambridge") $("showCambridge").checked = !$("showCambridge").checked;
  else if (kind === "owner") setOwnerOcc("plus", false);
  else if (kind.startsWith("weight:")) {
    const k = kind.slice(7);
    state.weights[k] = state.meta.default_weights[k];
    renderWeights();
  }
  // the agent's 5 picks no longer reflect the edited request: show the full ranked list instead
  state.agentIds = null;
  state.edited = true;
  renderUnderstood();
  await loadListings();
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
      body: JSON.stringify({ query: q, campus: state.campus, owner_occ: state.ownerOcc }) });
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
    $("showOlder").checked = !!f.include_stale;
    $("showCambridge").checked = !Array.isArray(f.cities);
    if (f.owner_occupied_pref) setOwnerOcc(f.owner_occupied_pref, false);
    state.areas = (f.areas || []).slice();
    state.plan = r.plan || {};
    state.edited = false;
    const g = r.grounding || {};
    const mode = r.mode === "llm" ? `AI agent (${esc(r.model)})` : "offline mode";
    box.innerHTML = `<div class="lbl">I read this as</div><div class="tags" id="chips"></div>
      <div class="hint">Click × to drop a filter, or a ↑ priority to reset it. ↑ = the agent raised this weight above its default.</div>
      <div class="verified${g.ok ? "" : " warn"}">${g.ok ? `✓ All ${g.numbers_checked} numbers checked against the records` : `⚠ Unverified numbers: ${esc((g.ungrounded || []).join(", "))}`} · ${mode}${r.fallback_reason ? " (AI unavailable)" : ""}</div>
      <details><summary>Read the agent’s explanation</summary><div class="explain">${mdToHtml(r.answer)}</div></details>`;
    renderUnderstood();
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
  state.areas = [];
  state.edited = false;
  state.plan = null;
  $("understood").classList.add("hidden");
  state.weights = { ...state.meta.default_weights };
  renderWeights();
  loadListings();
}

function setOwnerOcc(v, reload = true) {
  state.ownerOcc = v;
  $("ownerSeg").querySelectorAll("button").forEach((b) => b.setAttribute("aria-checked", b.dataset.v === v));
  if (state.plan) renderUnderstood();
  if (reload) { loadListings(); if (state.selected) openDetail(state.selected); }
}

/* ---------- about ---------- */
function snapshotHTML(s) {
  const f = s.funnel || {}, r = s.rules || {}, prev = s.previous;
  if (!f.retrieved) return "";
  const line = (k, v) => `<tr><td>${k}</td><td>${Number(v || 0).toLocaleString()}</td></tr>`;
  return `<h4>Listing snapshot: RentCast, pulled ${esc(s.pulled || s.date)}</h4><table>
    ${line("Listings retrieved", f.retrieved)}
    ${line("− not active / no price or location", (f.dropped_inactive || 0) + (f.dropped_no_price_or_location || 0))}
    ${line("− outside Allston, Brighton, Fenway, Cambridge", f.dropped_outside_scope)}
    ${line(`− not seen active in the ${r.not_seen_days} days before the pull`, f.dropped_not_seen_recently)}
    ${line(`− listed more than ${r.backup_days} days ago`, f.dropped_older_than_backup)}
    ${line(`= shown (listed ≤ ${r.fresh_days} days ago)`, f.fresh)}
    ${line(`+ older backups (${r.fresh_days + 1}–${r.backup_days} days, hidden by default)`, f.older)}
  </table>${prev ? `<p>Since the ${esc(prev.date)} pull: ${prev.gone} of ${prev.listings} listings disappeared (likely rented), ${prev.new} are new.</p>` : ""}
  <p>One provider’s listings, not the whole rental market.</p>`;
}

function coverageHTML(c) {
  if (!c.boston_listings) return "";
  const pct = (n) => `${n} <span style="color:var(--ink-3)">(${Math.round(100 * n / c.boston_listings)}%)</span>`;
  return `<h4>Coverage of Boston listings (${c.boston_listings})</h4><table>
    <tr><td>Address matched to a city parcel</td><td>${pct(c.found_in_city_parcels)}</td></tr>
    <tr><td>Owner of record found</td><td>${pct(c.owner_of_record)}</td></tr>
    <tr><td>Owner occupancy known</td><td>${pct(c.owner_occupancy_known)}</td></tr>
    <tr><td>With complaint / violation records</td><td>${pct(c.with_city_records)}</td></tr>
    <tr><td>Known address, no records (limited evidence)</td><td>${pct(c.no_records_found)}</td></tr>
    <tr><td>Not matched to city data</td><td>${pct(c.unmatched)}</td></tr>
  </table><p>Cambridge: ${c.cambridge_listings_listing_only} listings, listing data only (no complaint or owner records yet).</p>`;
}

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
    <p>Built ${esc(b.as_of || "?")}${b.fixtures ? " · SYNTHETIC TEST DATA" : ""} · city records through ${esc((b.records_through || "?").slice(0, 10))} · AI: ${esc(state.meta.llm || "offline mode")}</p>
    ${snapshotHTML(b.snapshot || {})}
    ${coverageHTML(b.coverage || {})}
    <h4>How the score works</h4>
    <p>A weighted average of the factors under “Adjust”. Factors with no data are left out, never guessed. A building with no records scores at most 90: no records is limited evidence, not a guarantee.</p>
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
  ["maxPrice", "minBeds"].forEach((id) => $(id).addEventListener("input", () => { if (state.plan) renderUnderstood(); debounce(loadListings); }));
  $("showOlder").addEventListener("change", () => { if (state.plan) renderUnderstood(); loadListings(); });
  $("showCambridge").addEventListener("change", () => { if (state.plan) renderUnderstood(); loadListings(); });
  $("sort").addEventListener("change", (e) => { state.sort = e.target.value; renderCards(); });
  $("ownerSeg").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => setOwnerOcc(b.dataset.v)));
  $("resetW").addEventListener("click", () => { state.weights = { ...state.meta.default_weights }; renderWeights(); setOwnerOcc("plus", false); loadListings(); });
  $("closeDetail").addEventListener("click", () => { $("detail").classList.add("hidden"); state.selected = null;
    document.querySelectorAll(".card.on").forEach((c) => c.classList.remove("on")); });
  $("aboutBtn").addEventListener("click", () => $("about").showModal());
  $("closeAbout").addEventListener("click", () => $("about").close());
  await loadListings();
}
init().catch((e) => { $("cards").innerHTML = `<li class="verified warn">Error: ${esc(e.message)}</li>`; });
