import { Globe } from "./globe.js";
import { applyStatic, getLang, locale, setLang, t } from "./i18n.js";
import { CURRENCIES, INTERESTS, closeDash, esc, initAccount, logActivity, onTripPlanned, refreshAccountLanguage } from "./account.js";
import { closeEvents, initEvents, openEvents, refreshEventsLanguage } from "./events.js";
import { initLandmarks } from "./landmark.js";
import { mountBuddies } from "./buddies.js";
import { closePilgrimage, initPilgrimage, refreshPilgrimageLanguage } from "./pilgrimage.js";

const $ = (id) => document.getElementById(id);
// Links come from third-party data: only http(s) URLs are ever put in an href.
const safeUrl = (u) => (/^https?:\/\//i.test(String(u || "").trim()) ? esc(String(u).trim()) : "#");

// ------------------------------------------------------------------ icons
const P = {
  plane: "M21 16v-2l-8-5V3.5a1.5 1.5 0 0 0-3 0V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5z",
  bed: "M3 18v-7h18v7M3 14h18M7 11V8h4v3",
  fork: "M7 3v8M5 3v4a2 2 0 0 0 4 0V3M7 11v10M16 3c-2 0-3 3-3 6s1 4 3 4v8",
  landmark: "M3 21h18M5 21V10M19 21V10M9 21v-7M15 21v-7M12 3l9 5H3z",
  route: "M6 19a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM18 9a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM8 17h6a3 3 0 0 0 0-6h-4a3 3 0 0 1 0-6h6",
  cloud: "M7 18h10a4 4 0 0 0 0-8 6 6 0 0 0-11.5 1.5A3.5 3.5 0 0 0 7 18z",
  rain: "M7 15h10a4 4 0 0 0 0-8 6 6 0 0 0-11.5 1.5A3.5 3.5 0 0 0 7 15zM8 18l-1 3M12 18l-1 3M16 18l-1 3",
  storm: "M7 15h10a4 4 0 0 0 0-8 6 6 0 0 0-11.5 1.5A3.5 3.5 0 0 0 7 15zM13 15l-2 3.5h3L12 22",
  sun: "M12 7a5 5 0 1 0 0 10 5 5 0 0 0 0-10zM12 1v2M12 21v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M1 12h2M21 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4",
  snow: "M12 2v20M4 7l16 10M4 17L20 7",
  coins: "M12 3c4 0 7 1.3 7 3s-3 3-7 3-7-1.3-7-3 3-3 7-3zM5 6v6c0 1.7 3 3 7 3s7-1.3 7-3V6M5 12v6c0 1.7 3 3 7 3s7-1.3 7-3v-6",
  brain: "M12 3a4 4 0 0 0-4 4 4 4 0 0 0-3 7 4 4 0 0 0 7 4 4 4 0 0 0 7-4 4 4 0 0 0-3-7 4 4 0 0 0-4-4zM12 3v18",
  pin: "M12 21s7-6.5 7-12a7 7 0 0 0-14 0c0 5.5 7 12 7 12zM12 11a2 2 0 1 0 0-4 2 2 0 0 0 0 4z",
  shield: "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6zM9 12l2 2 4-4",
  wrench: "M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.5 2.5-2.4-.6-.6-2.4z",
  star: "M12 3l2.8 5.8 6.2.9-4.5 4.4 1 6.2L12 17.4 6.5 20.3l1-6.2L3 9.7l6.2-.9z",
  chat: "M4 5h16v11H9l-5 4z",
  search: "M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM21 21l-5-5",
  sparkle: "M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8zM19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z",
  check: "M5 12l5 5L20 7",
  x: "M6 6l12 12M18 6L6 18",
  alert: "M12 8v5M12 16.5v.5M10.3 3.9L2 18a2 2 0 0 0 1.7 3h16.6A2 2 0 0 0 22 18L13.7 3.9a2 2 0 0 0-3.4 0z",
  walk: "M13 4a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3zM9 22l2-7 3 3v6M7 13l2-5 4 1 3 4M11 15l-2-3",
  transit: "M5 17V6a3 3 0 0 1 3-3h8a3 3 0 0 1 3 3v11zM5 12h14M8 17v3M16 17v3",
  taxi: "M5 16l1.5-5h11L19 16M4 16h16v3H4zM7 19v2M17 19v2",
  coffee: "M4 8h13v5a5 5 0 0 1-5 5H9a5 5 0 0 1-5-5zM17 9h1a3 3 0 0 1 0 6h-1M8 2v3M12 2v3",
  moon: "M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z",
  clock: "M12 7v5l3 2M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z",
  link: "M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1",
  globe: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM3 12h18M12 3c3 3 4 6 4 9s-1 6-4 9M12 3c-3 3-4 6-4 9s1 6 4 9",
};
const icon = (n) => `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${P[n] || P.sparkle}"/></svg>`;

// ------------------------------------------------------------------ state
// turn: id of the chat turn whose answer may still change the screen (a newer turn or a new trip retires it).
const state = { tripId: null, trip: null, tab: "itinerary", day: 1, busy: false, map: null, routeKey: "", turn: 0, ctrl: null };
// "?q=Plan a trip to Rome" (from a travel guide page): start a new trip with that request ready to complete.
const PREFILL = new URLSearchParams(location.search).get("q");
try { state.tripId = PREFILL ? null : localStorage.getItem("tripId"); } catch (_) { /* storage unavailable */ }
if (PREFILL) {
  try { localStorage.removeItem("tripId"); } catch (_) { /* storage unavailable */ }
  queueMicrotask(() => {
    setText($("qcInput"), PREFILL.slice(0, 300) + " ");
    $("qcInput").focus();
    history.replaceState(null, "", location.pathname);  // a reload shouldn't refill it
  });
}
const globe = new Globe($("globe"), $("globeLabels"));
// The mouse wheel over the globe keeps scrolling the home page (dragging still spins the globe).
$("globe").addEventListener("wheel", (e) => { if (!$("hero").hidden) $("hero").scrollBy({ top: e.deltaY }); }, { passive: true });
window.voyageGlobe = globe;  // handy for debugging the 3D view from the console

// ------------------------------------------------------------------ helpers
function money(amount, cur) {
  const sym = { USD: "$", EUR: "€", GBP: "£" }[cur];
  const n = Math.round(amount).toLocaleString();
  return sym ? `${sym}${n}` : `${n} ${cur}`;
}
const userCur = () => state.trip?.trip_contract?.budget?.currency || "USD";
function toUser(m) {
  if (!m) return 0;
  if (m.currency === userCur()) return m.amount;
  return m.amount * ((state.trip.research && state.trip.research.fx_rates[m.currency]) || 1);
}
/**
 * Every price says how sure it is:
 *   known      ✓ published (Google fares & rates, Wikivoyage listing, quoted official fare) - source on hover
 *   range      a published per-person range (e.g. Google's "€10–20")
 *   calculated the official tariff applied to the real road distance (taxis)
 *   estimated  no published price: shown as an estimate, or hidden where it would look like a fact (hideEstimate)
 */
function costLabel(m, { hideEstimate = false } = {}) {
  if (!m || !m.amount) return "";
  const src = m.source ? esc(m.source) : "";
  if (m.price_type === "estimated") {
    const ai = (m.source || "").startsWith("AI estimate");
    const ref = (m.source || "").startsWith("Wikivoyage");  // an older published price
    if (ai || ref) return `≈ ${money(toUser(m), userCur())} <span class="badge ${ai ? "ai-est" : "info"}" title="${src}">${ai ? t("aiEst") : t("oldPrice")}</span>`;
    if (hideEstimate) return `<span class="price-na" title="${t("naTip")}">${t("priceNA")}</span>`;
    return `≈ ${money(toUser(m), userCur())} <span class="badge info" title="${t("estTip")}">${t("est")}</span>`;
  }
  const badge = m.price_type === "calculated" ? `<span class="badge tariff" title="${src || t("tariffTip")}">${t("tariff")}</span>`
    : m.price_type === "range" ? `<span class="badge range" title="${src || t("rangeTip")}">${t("range")}</span>`
      : `<span class="badge ok verified" title="${src || t("verifiedTip")}">✓</span>`;
  return `${money(toUser(m), userCur())} ${badge}`;
}

/** How much of the plan's cost rests on published prices (verified / calculated / estimated), in the user currency. */
function priceCertainty(plan) {
  const out = { verified: 0, calculated: 0, ai: 0, estimated: 0 };
  const add = (m, mult = 1) => {
    if (!m || !m.amount) return;
    const v = toUser(m) * mult;
    const informed = /^(AI estimate|Wikivoyage)/.test(m.source || "");  // a place-specific estimate, not a generic one
    out[m.price_type === "estimated" ? (informed ? "ai" : "estimated") : m.price_type === "calculated" ? "calculated" : "verified"] += v;
  };
  const pax = state.trip.trip_contract.travelers;
  const flights = plan.legs?.length ? plan.legs : [plan.outbound_flight, plan.return_flight];
  flights.forEach((f) => f && add(f.price_per_person, pax));
  (plan.stops?.length ? plan.stops.map((s) => s.hotel) : [plan.hotel]).forEach((h) => h && add(h.total_price));
  plan.days.forEach((d) => d.items.forEach((i) => {
    if (i.kind !== "flight") add(i.cost);
    if (i.kind !== "transfer") add(i.transport_from_previous?.cost);
  }));
  return out;
}
const arrow = () => (getLang() === "ar" ? " ← " : " → ");
const PHONE = () => window.matchMedia("(max-width: 900px)").matches;
const fmtDate = (iso, opts = { month: "short", day: "numeric" }) => new Date(iso + "T12:00:00").toLocaleDateString(locale(), opts);
function md(text) {
  const lines = esc(text).split("\n");
  let out = "", list = false;
  for (const raw of lines) {
    const line = raw.replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/(^|[^*])\*(?!\s)(.+?)\*/g, "$1<i>$2</i>");
    if (/^\s*[-•]\s+/.test(line)) { if (!list) { out += "<ul>"; list = true; } out += `<li>${line.replace(/^\s*[-•]\s+/, "")}</li>`; }
    else { if (list) { out += "</ul>"; list = false; } if (line.trim()) out += `<p>${line}</p>`; }
  }
  return out + (list ? "</ul>" : "");
}
function weatherIcon(cond = "") {
  const c = cond.toLowerCase();
  if (/thunder|storm|violent/.test(c)) return ["storm", "storm"];
  if (/rain|drizzle|shower/.test(c)) return ["rain", "rain"];
  if (/snow/.test(c)) return ["snow", "snow"];
  if (/clear|sun/.test(c)) return ["sun", "sun"];
  return ["cloud", "cloud"];
}
function tilt(el, max = 9) {
  el.addEventListener("pointermove", (e) => {
    const r = el.getBoundingClientRect();
    const x = (e.clientX - r.left) / r.width - 0.5, y = (e.clientY - r.top) / r.height - 0.5;
    el.style.transform = `rotateX(${(-y * max).toFixed(2)}deg) rotateY(${(x * max).toFixed(2)}deg) translateZ(4px)`;
  });
  el.addEventListener("pointerleave", () => { el.style.transform = ""; });
}

// ------------------------------------------------------------------ chat
function addMessage(role, text, cls = "") {
  const div = document.createElement("div");
  div.className = `msg ${role} ${cls}`;
  div.dir = "auto";  // each message reads in its own direction (an Arabic reply in the English UI, and vice versa)
  div.innerHTML = role === "assistant" ? md(text) : esc(text);
  $("messages").appendChild(div);
  $("messages").scrollTop = $("messages").scrollHeight;
  return div;
}
function typing() {
  const div = document.createElement("div");
  div.className = "msg assistant typing";
  div.innerHTML = "<i></i><i></i><i></i>";
  $("messages").appendChild(div);
  $("messages").scrollTop = $("messages").scrollHeight;
  return div;
}
function setBusy(b, label) {
  state.busy = b;
  document.body.classList.toggle("busy", b);
  $("send").disabled = b;
  $("agentState").textContent = label || (b ? t("working") : t("ready"));
}

/** An HTTP error with what the server said (and how long to wait after a rate limit). */
async function httpError(res) {
  let detail = "";
  try { const j = await res.json(); detail = typeof j.detail === "string" ? j.detail : ""; } catch (_) { /* not JSON */ }
  const err = new Error(detail || res.statusText);
  err.status = res.status;
  err.retry = res.headers.get("Retry-After");
  return err;
}
function errorText(err) {
  if (err.status === 429) return t("errRate", err.retry || "60");
  if (err.status === 400 || err.status === 422) return t("errTooLong");
  return t("errNet");
}

/** Stop listening to the running turn (a new trip, another trip opened): its answer must not land on this screen. */
function retireTurn() {
  state.turn += 1;
  if (state.ctrl) state.ctrl.abort();
  state.ctrl = null;
  if (state.busy) setBusy(false);
}

/** Send a chat message. Returns false when it wasn't sent (a turn is still running, or nothing to send). */
async function send(text, extra = {}) {
  if (state.busy || !text.trim()) return false;
  document.querySelectorAll(".route-actions").forEach((el) => el.remove());
  openChat();
  addMessage("user", text);
  const ctx = { dots: typing(), failed: false };
  setBusy(true, t("understanding"));
  const turn = ++state.turn;
  const ctrl = state.ctrl = new AbortController();
  const pulse = setInterval(() => globe.pulse(), 1200);
  try {
    const res = await fetch("/api/chat/stream", {
      method: "POST", headers: { "Content-Type": "application/json" }, signal: ctrl.signal,
      body: JSON.stringify({ message: text, trip_id: state.tripId, preview: true, ...extra }),
    });
    if (!res.ok || !res.body) throw await httpError(res);
    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const raw = buf.slice(0, i);
        buf = buf.slice(i + 2);
        if (raw.startsWith("data: ") && turn === state.turn) handleEvent(JSON.parse(raw.slice(6)), ctx);
      }
    }
  } catch (err) {
    if (turn !== state.turn || err.name === "AbortError") return true;
    ctx.dots.remove();
    console.error(err);
    addMessage("assistant", errorText(err), "error");
  } finally {
    clearInterval(pulse);
    if (turn === state.turn) { setBusy(false); state.ctrl = null; }
  }
  return true;
}

function handleEvent(ev, ctx) {
  if (ev.type === "node") {
    const label = t("node")[ev.node];
    if (label) $("agentState").textContent = label;
  } else if (ev.type === "tool") {
    const label = t("tool")[ev.server];
    if (label) $("agentState").textContent = label;
  } else if (ev.type === "error") {
    ctx.dots.remove();
    ctx.failed = true;
    console.error(ev.message);
    addMessage("assistant", t("errPlan"), "error");
  } else if (ev.type === "preview" && !ctx.failed) {
    // The new plan, shown while the expert reviews it and the reply is written (the reply then updates it).
    showPlan(ev.trip);
  } else if (ev.type === "done" && !ctx.failed) {
    ctx.dots.remove();
    state.tripId = ev.trip_id;
    try { localStorage.setItem("tripId", ev.trip_id); } catch (_) { /* ignore */ }
    const msg = ev.reply ? addMessage("assistant", ev.reply) : null;
    if (msg) notify("chat");
    pathButton(msg, ev.trip.metadata);
    showPlan(ev.trip);
    const pr = ev.trip.draft && ev.trip.draft.route_proposal;
    if (msg && pr && pr.stops.length && !ev.trip.draft.route_confirmed) routeActions(msg, pr);
  }
}
function showPlan(trip) {
  const firstPlan = !Object.keys(state.trip?.plans || {}).length;
  setTrip(trip);
  // Phones: the first plan opens on its own screen (the reply then lands in the chat, with a dot on its tab).
  if (PHONE() && firstPlan && Object.keys(trip.plans || {}).length) setView("trip");
  else if (Object.keys(trip.plans || {}).length) notify("trip");
}

// A proposed route: one click to accept it (language-independent), or type any change in your own words.
function routeActions(after, pr) {
  const box = document.createElement("div");
  box.className = "route-actions";
  box.innerHTML = `<div class="ra-route">${pr.stops.map((s, i) => `<span><i>${i + 1}</i>${esc(s.city)} · ${s.nights}${t("nShort")}</span>`).join('<b class="tr-arrow">→</b>')}</div>
    <button class="btn primary" type="button">${icon("route")}${t("planRoute")}</button>
    <span class="muted">${t("orChange")}</span>`;
  box.querySelector("button").addEventListener("click", () => send("✓ " + pr.stops.map((s) => s.city).join(arrow()), { route_decision: "accept" }));
  after.after(box);
  $("messages").scrollTop = $("messages").scrollHeight;
}

function renderChips() {
  // Only the agents' own next-step ideas, written for this trip and this traveller (no fixed quick replies).
  const ideas = (state.trip?.metadata?.suggestions || []).filter(Boolean);
  const chips = ideas.map((c) => [c, true]);
  $("chips").hidden = !chips.length;
  $("chips").innerHTML = chips.map(([c, ai]) => `<button class="chip${ai ? " ai" : ""}" type="button" dir="auto" title="${esc(c)}" data-say="${esc(c)}">${ai ? "✨ " : ""}${esc(c)}</button>`).join("");
  $("chips").querySelectorAll(".chip").forEach((b) => b.addEventListener("click", () => send(b.dataset.say)));
}

// ------------------------------------------------------------------ trip + globe
function setTrip(t) {
  const prev = state.trip;
  const wasPlanned = !!(prev && prev.plans && Object.keys(prev.plans).length);
  state.trip = t;
  const plan = t && t.plans && t.plans[t.selected_mode];
  if (plan && (!wasPlanned || prev.trip_id !== t.trip_id)) onTripPlanned(t);
  document.body.classList.toggle("has-trip", !!plan);
  $("board").hidden = !plan;
  $("hero").hidden = !!plan;
  // Globe: keep spinning until the destination(s) are known, then lock onto the whole route.
  const c = t && t.trip_contract;
  const o = (c && c.origin_ref) || (t && t.draft && t.draft.origin_ref);
  const stops = routeStops(t);
  const key = `${o?.name}|${stops.map((s) => s.name).join(">")}`;
  if (key !== state.routeKey && stops.length) {
    state.routeKey = key;
    const pt = (r) => r && { lat: r.lat, lon: r.lon, name: r.name };
    globe.setJourney(pt(o), stops.map(pt));
  }
  renderChips();
  if (plan) {
    if (state.day > plan.days.length) state.day = 1;
    renderBoard();
  }
  requestAnimationFrame(layoutGlobe);
}

function routeStops(t) {
  if (!t) return [];
  const c = t.trip_contract, d = t.draft || {};
  // A route awaiting the traveller's answer is shown on the globe right away.
  if (d.route_proposal && !d.route_confirmed && d.route_proposal.stops.length) {
    return d.route_proposal.stops.map((s) => s.ref).filter(Boolean);
  }
  if (c && c.stops && c.stops.length > 1) return c.stops.map((s) => s.ref);
  if (d.destination_refs && d.destination_refs.length > 1) return d.destination_refs;
  const one = (c && c.destination_ref) || d.destination_ref;
  return one ? [one] : [];
}
const isMulti = (plan) => !!(plan && plan.stops && plan.stops.length > 1);
function stopForDay(plan, day) {
  if (!isMulti(plan)) return null;
  return plan.stops.find((s) => s.name === day.city) || plan.stops.find((s) => day.day >= s.first_day && day.day <= s.last_day);
}

function layoutGlobe() {
  if (window.innerWidth <= 900) { globe.setCenterOffset(0); globe.setSafeArea(24, window.innerWidth - 24); return; }
  // Layout boxes (offset*) rather than getBoundingClientRect: the board may still be sliding in.
  // Works in both directions: in Arabic (RTL) the chat sits on the right and the board on the left.
  let left = 0, right = window.innerWidth;
  for (const p of [$("chatPanel"), $("board")]) {
    if (p.hidden || !p.offsetWidth) continue;
    if (p.offsetLeft + p.offsetWidth / 2 < window.innerWidth / 2) left = Math.max(left, p.offsetLeft + p.offsetWidth);
    else right = Math.min(right, p.offsetLeft);
  }
  // Home: the globe takes the half of the screen the trip box doesn't use.
  const box = !document.body.classList.contains("has-trip") && $("compose").getBoundingClientRect();
  if (box && box.width) {
    if (box.left + box.width / 2 < window.innerWidth / 2) left = Math.max(left, box.right);
    else right = Math.min(right, box.left);
  }
  globe.setCenterOffset((left + right) / 2 - window.innerWidth / 2);
  globe.setSafeArea(left + 40, right - 40);
}
window.addEventListener("resize", layoutGlobe);

function renderBoard() {
  const trip = state.trip, c = trip.trip_contract, plan = trip.plans[trip.selected_mode];
  const d = c.destination_ref || {};
  const nDays = Math.round((new Date(c.end_date) - new Date(c.start_date)) / 86400000) + 1;
  const multi = isMulti(plan);
  const countries = multi ? [...new Set(plan.stops.map((s) => s.country).filter(Boolean))].join(" · ") : d.country;
  $("tripEyebrow").textContent = [multi ? t("cityJourney", plan.stops.length) : "", countries, t("days", nDays), t("nights", nDays - 1)]
    .filter(Boolean).join(" · ");
  const cn = d.country && c.destination_name.toLowerCase().endsWith(" " + d.country.toLowerCase())
    ? c.destination_name.slice(0, -d.country.length).trim() : c.destination_name;
  $("tripTitle").textContent = multi ? plan.stops.map((s) => s.name).join(arrow()) : cn;
  $("routeStrip").hidden = !multi;
  $("routeStrip").innerHTML = multi ? routeStrip(plan, c) : "";
  $("routeStrip").querySelectorAll("[data-day]").forEach((b) => b.addEventListener("click", () => {
    state.day = +b.dataset.day; state.tab = "itinerary"; renderTab();
  }));
  const stayTab = document.querySelector('#tabs [data-tab="stay"]');
  stayTab.dataset.i18n = multi ? "tabs.stayMulti" : "tabs.stay";
  stayTab.textContent = t(stayTab.dataset.i18n);
  $("tripSub").textContent = `${fmtDate(c.start_date, { weekday: "short", month: "short", day: "numeric" })}${arrow()}${fmtDate(c.end_date, { weekday: "short", month: "short", day: "numeric" })} · ${t("travellers", c.travelers)} · ${t("from")} ${c.origin_city} · ${t("budgetWord")} ${money(c.budget.amount, c.budget.currency)}`;
  // Parts that came from the AI fallback (live search unavailable) are flagged.
  const legs = (plan.legs && plan.legs.length ? plan.legs : [plan.outbound_flight, plan.return_flight]).filter(Boolean);
  const hotels = (plan.stops && plan.stops.length ? plan.stops.map((s) => s.hotel) : [plan.hotel]).filter(Boolean);
  const ai = [...legs, ...hotels].some((x) => x.metadata && x.metadata.source === "ai_knowledge");
  if (ai) $("tripSub").insertAdjacentHTML("beforeend", ` <span class="badge warn" title="${t("aiBadgeTip")}">${t("aiBadge")}</span>`);
  $("bookLink").href = `/api/trips/${trip.trip_id}/book`;
  renderModes();
  renderTab();
}

const LEG_MODE_ICON = { flight: "plane", train: "transit", coach: "transit", car: "taxi" };
const STOP_COLORS = ["#3de0d0", "#8b7bff", "#ff6fa3", "#6fe38a", "#4fb3ff", "#ffd166", "#ffb454"];
function routeStrip(plan, c) {
  const leg = (f) => f ? `<span class="rs-leg ${f.mode}" title="${esc(`${f.airline} ${f.flight_number} · ${f.depart_at.slice(11, 16)}`)}">
    ${icon(LEG_MODE_ICON[f.mode] || "plane")}<small>${f.mode === "flight" ? esc(f.airline.split(" + ")[0]) : f.mode}</small></span>` : `<span class="rs-leg">${icon("route")}</span>`;
  const home = `<span class="rs-stop home"><b>${esc(c.origin_city)}</b><small>${t("home")}</small></span>`;
  // The trip may end in another city than it started (fly home to Cairo after starting in Riyadh).
  const end = c.return_city ? `<span class="rs-stop home"><b>${esc(c.return_city)}</b><small>${t("home")}</small></span>` : home;
  const stops = plan.stops.map((s, i) => `${leg(plan.legs[i])}<button class="rs-stop" type="button" data-day="${s.first_day}" style="--c:${STOP_COLORS[(i + 1) % STOP_COLORS.length]}">
      <i>${i + 1}</i><b>${esc(s.name)}</b><small>${t("nights", s.nights)} · ${fmtDate(s.start_date)}</small></button>`).join("");
  return `${home}${stops}${leg(plan.legs[plan.legs.length - 1])}${end}`;
}

function ring(score, size = 46) {
  const r = size / 2 - 4, circ = 2 * Math.PI * r;
  return `<div class="ring" style="width:${size}px;height:${size}px"><svg viewBox="0 0 ${size} ${size}" style="width:${size}px;height:${size}px"><circle class="bg" cx="${size / 2}" cy="${size / 2}" r="${r}"/>
    <circle class="fg" cx="${size / 2}" cy="${size / 2}" r="${r}" stroke-dasharray="${circ}" stroke-dashoffset="${circ}" data-target="${circ * (1 - score / 100)}"/></svg><b>${score}</b></div>`;
}
function animateRings(root) {
  requestAnimationFrame(() => root.querySelectorAll(".ring .fg").forEach((c) => { c.style.strokeDashoffset = c.dataset.target; }));
}

function renderModes() {
  const trip = state.trip;
  const order = ["balanced", "budget", "comfort", "experience"];
  $("modes").innerHTML = order.filter((m) => trip.plans[m]).map((m) => {
    const p = trip.plans[m];
    const pitch = getLang() === "ar" ? (p.pitch_ar || p.pitch) : p.pitch;
    return `<button class="mode ${m === trip.selected_mode ? "active" : ""}" data-mode="${m}" type="button">
      <div class="m-name">${t("mode")[m]}</div>
      ${pitch ? `<div class="m-pitch" title="${esc(pitch)}">${esc(pitch)}</div>` : ""}
      <div class="m-row">${ring(p.score ? p.score.total : 0)}<div><div class="m-total">${money(p.budget.total, p.budget.currency)}</div>
      <span class="badge ${p.within_budget ? "ok" : "bad"}">${p.within_budget ? t("inBudget") : t("overBudget")}</span></div></div>
      <div class="m-hotel">${esc(isMulti(p) ? t("hotelsLegs", p.stops.length, p.legs.length) : (p.hotel ? p.hotel.name : ""))}</div></button>`;
  }).join("");
  $("modes").querySelectorAll(".mode").forEach((b) => {
    tilt(b, 10);
    b.addEventListener("click", async () => {
      if (state.busy) return addMessage("assistant", t("busyWait"));
      const res = await fetch(`/api/trips/${trip.trip_id}/select`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ mode: b.dataset.mode }) });
      if (res.ok) setTrip(await res.json());
    });
  });
  animateRings($("modes"));
}

/** Scroll a horizontal strip (never the page) so `el` is fully visible. */
function revealInStrip(strip, el) {
  if (!strip || !el) return;
  const s = strip.getBoundingClientRect(), r = el.getBoundingClientRect();
  if (r.left < s.left) strip.scrollBy({ left: r.left - s.left - 16, behavior: "smooth" });
  else if (r.right > s.right) strip.scrollBy({ left: r.right - s.right + 16, behavior: "smooth" });
}
function renderTab() {
  document.querySelectorAll("#tabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === state.tab)));
  revealInStrip($("tabs"), document.querySelector('#tabs [aria-selected="true"]'));
  const plan = state.trip.plans[state.trip.selected_mode];
  if (state.map) { state.map.remove(); state.map = null; }
  const views = { itinerary, stay, budget, checks, weather, profile, sources, buddies: () => "" };
  $("panel").innerHTML = views[state.tab](plan);
  $("panel").scrollTop = 0;
  if (state.tab === "buddies") mountBuddies($("panel"), state.trip);
  $("panel").querySelectorAll("[data-offers]").forEach((b) => b.addEventListener("click", () => openOffers(b.dataset.offers)));
  $("panel").querySelectorAll("[data-suggest]").forEach((b) => b.addEventListener("click", () => send(b.dataset.suggest)));
  if (state.tab === "itinerary") {
    wireItinerary(plan);
    revealInStrip($("panel").querySelector(".days"), $("panel").querySelector(".day-pill.active"));
  }
  if (state.tab === "budget") {
    wireWhatIf();
    $("curSel").addEventListener("change", (e) => {
      const cur = e.target.value;
      e.target.value = plan.budget.currency;  // the switch shows the trip's real currency until the new plan arrives
      if (!state.busy && cur !== plan.budget.currency) send(t("currencyMsg", cur));
    });
  }
  if (state.tab === "checks") animateRings($("panel"));
}

// ------------------------------------------------------------------ itinerary
const KIND_ICON = { meal: "fork", activity: "landmark", transfer: "route", flight: "plane", hotel: "bed", rest: "moon", free: "clock" };
const LEG_ICON = { walk: "walk", transit: "transit", taxi: "taxi", train: "transit", bus: "transit" };

function itinerary(plan) {
  const d = plan.days[state.day - 1];
  const pills = plan.days.map((x) => {
    const [ic] = weatherIcon(x.weather?.condition);
    const s = stopForDay(plan, x);
    const city = s ? `<em style="--c:${STOP_COLORS[(s.index + 1) % STOP_COLORS.length]}">${x.travel_day ? "→ " : ""}${esc(s.name)}</em>` : "";
    return `<button class="day-pill ${x.day === state.day ? "active" : ""} ${x.travel_day ? "travel" : ""}" data-day="${x.day}" type="button"><b>${t("day")} ${x.day}</b>
      <span>${icon(x.travel_day ? "plane" : ic)}${fmtDate(x.date, { weekday: "short", day: "numeric" })}</span>${city}</button>`;
  }).join("");
  let n = 0;
  const items = d.items.map((i, idx) => {
    const leg = i.transport_from_previous && i.kind !== "transfer"
      ? `<div class="t-leg">${icon(LEG_ICON[i.transport_from_previous.mode] || "route")}${i.transport_from_previous.minutes} ${t("min")} · ${i.transport_from_previous.distance_km.toFixed(1)} km</div>` : "";
    const numbered = i.location && ["activity", "meal"].includes(i.kind);
    if (numbered) n += 1;
    const more = [];
    if (i.explanation?.length) more.push(`<b>${t("why")}</b> ${i.explanation.map(esc).join(" · ")}`);
    if (i.notes) more.push(esc(i.notes));
    if (i.alternatives?.length) more.push(`<b>${t("alternatives")}</b> ${i.alternatives.map(esc).join(", ")}`);
    const asked = i.explanation?.[0] === "You asked to visit this place";
    return `${leg}<div class="t-item ${i.kind}${asked ? " requested" : ""}" style="animation-delay:${idx * 40}ms">
      <span class="t-dot">${numbered ? n : icon(KIND_ICON[i.kind] || "sparkle").replace("<svg", '<svg style="width:10px;height:10px"')}</span>
      <div class="t-head"><span class="t-time">${i.start}–${i.end}</span><span class="t-cost">${costLabel(i.cost, { hideEstimate: i.kind === "meal" || i.kind === "activity" })}</span></div>
      <div class="t-title">${esc(i.title)}${asked ? ` <span class="badge asked">${t("youAsked")}</span>` : ""}${i.explanation?.[0]?.startsWith("Added by the expert review") ? ` <span class="badge expert">${t("expertPick")}</span>` : ""}${i.explanation?.[0] === "Because you love the sea" ? ` <span class="badge info">${t("forYou")}</span>` : ""}</div>
      ${i.place_id ? placeLinks(findPlace(i.place_id)) : ""}
      ${more.length ? `<details class="t-more"><summary>${t("details")}</summary>${more.join("<br>")}</details>` : ""}</div>`;
  }).join("");
  const dayStop = stopForDay(plan, d);
  const route = dayRouteUrl(d, dayStop ? dayStop.hotel : plan.hotel);
  const w = d.weather;
  const meta = [
    w ? `<span class="badge ${w.risk === "high" ? "bad" : w.risk === "medium" ? "warn" : "ok"}">${esc(w.condition)} · ${Math.round(w.temp_min_c)}–${Math.round(w.temp_max_c)}°C</span>` : "",
    `<span class="badge info">${t("walk")} ${d.walking_km.toFixed(1)} km</span>`,
    `<span class="badge info">${money(d.estimated_cost.amount, d.estimated_cost.currency)} ${t("today")}</span>`,
  ].join("");
  return `<div class="days">${pills}</div>
    <div class="day-view"><div><h3 class="day-title">${esc(d.title)}</h3><div class="day-meta">${meta}</div></div>
    <div class="map" id="dayMap"></div>
    ${route ? `<a class="route-link" href="${safeUrl(route)}" target="_blank" rel="noopener">${icon("route")}${t("dayRoute")}</a>` : ""}
    ${d.notes.map((x) => `<div class="note">${esc(x)}</div>`).join("")}
    <div class="timeline">${items}</div></div>`;
}

function wireItinerary(plan) {
  $("panel").querySelectorAll(".day-pill").forEach((b) => b.addEventListener("click", () => { state.day = +b.dataset.day; renderTab(); }));
  const d = plan.days[state.day - 1];
  const el = $("dayMap");
  if (!window.L || !el) { if (el) el.remove(); return; }
  const map = L.map(el, { zoomControl: true, attributionControl: true, scrollWheelZoom: false,
    dragging: !window.matchMedia("(pointer: coarse)").matches });
  state.map = map;
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "© OpenStreetMap contributors", maxZoom: 19, className: "dark-tiles",
  }).addTo(map);
  const pts = [];
  const stop = stopForDay(plan, d);
  const hotel = stop ? stop.hotel : plan.hotel;
  if (hotel && !(d.travel_day && stop)) {
    const h = [hotel.location.lat, hotel.location.lon];
    L.marker(h, { icon: L.divIcon({ className: "", html: '<div class="pin hotel"><b>H</b></div>', iconSize: [24, 24], iconAnchor: [12, 24] }), title: hotel.name }).addTo(map).bindTooltip(esc(hotel.name));
    pts.push(h);
  }
  let n = 0;
  for (const i of d.items) {
    if (!i.location || !["activity", "meal"].includes(i.kind)) continue;
    n += 1;
    const p = [i.location.lat, i.location.lon];
    pts.push(p);
    L.marker(p, { icon: L.divIcon({ className: "", html: `<div class="pin ${i.kind}"><b>${n}</b></div>`, iconSize: [24, 24], iconAnchor: [12, 24] }) })
      .addTo(map).bindTooltip(esc(`${i.start} · ${i.title}`));
  }
  if (d.travel_day && stop) {
    // Moving day between cities: show the arrival city's side of the day (the journey itself is on the globe).
    const here = pts.filter(([la, lo]) => stop && Math.hypot(la - stop.location.lat, lo - stop.location.lon) < 0.6);
    pts.length = 0;
    if (stop && stop.hotel) {
      const h = [stop.hotel.location.lat, stop.hotel.location.lon];
      L.marker(h, { icon: L.divIcon({ className: "", html: '<div class="pin hotel"><b>H</b></div>', iconSize: [24, 24], iconAnchor: [12, 24] }) }).addTo(map).bindTooltip(esc(stop.hotel.name));
      pts.push(h);
    }
    pts.push(...here);
  }
  if (pts.length > 1) {
    L.polyline(pts, { color: "#0b1220", weight: 7, opacity: 0.7 }).addTo(map);
    L.polyline(pts, { color: "#3de0d0", weight: 4, opacity: 1, className: "route-line" }).addTo(map);
  }
  const centre = stop ? stop.location : state.trip.trip_contract.destination_ref;
  if (pts.length) map.fitBounds(pts, { padding: [28, 28], maxZoom: 15 });
  else map.setView([centre.lat, centre.lon], 12);
  setTimeout(() => { if (state.map === map) map.invalidateSize(); }, 60);  // unless it was redrawn meanwhile
}

// ------------------------------------------------------------------ reference links (every place is checkable)
function findPlace(id) {
  const r = state.trip && state.trip.research;
  return r ? [...r.attractions, ...r.restaurants].find((p) => p.id === id) : null;
}
function mapsUrl(p) {
  if (p.google_place_id) return `https://www.google.com/maps/place/?q=place_id:${encodeURIComponent(p.google_place_id)}`;
  return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(`${p.name} ${p.address || ""}`.trim())}`;
}
function placeLinks(p) {
  if (!p) return "";
  const links = [`<a href="${safeUrl(mapsUrl(p))}" target="_blank" rel="noopener">${icon("pin")}${t("mapsLink")}</a>`];
  if (p.website) links.push(`<a href="${safeUrl(p.website)}" target="_blank" rel="noopener">${icon("globe")}${t("website")}</a>`);
  if (p.menu_url) links.push(`<a href="${safeUrl(p.menu_url)}" target="_blank" rel="noopener">${icon("fork")}${t("menu")}</a>`);
  if (p.booking_url) links.push(`<a class="hot" href="${safeUrl(p.booking_url)}" target="_blank" rel="noopener">${icon(p.kind === "attraction" ? "star" : "fork")}${t(p.kind === "attraction" ? "tickets" : "reserve")}</a>`);
  return `<div class="t-links">${links.join("")}</div>`;
}
/** The whole day as a Google Maps route: hotel -> each stop, in order. */
function dayRouteUrl(day, hotel) {
  const pts = day.items.filter((i) => i.location && ["activity", "meal"].includes(i.kind)).map((i) => `${i.location.lat},${i.location.lon}`);
  if (!pts.length) return null;
  const origin = hotel ? `${hotel.location.lat},${hotel.location.lon}` : pts[0];
  const destination = pts[pts.length - 1];
  const waypoints = pts.slice(hotel ? 0 : 1, -1).slice(0, 8).join("|");
  return `https://www.google.com/maps/dir/?api=1&origin=${origin}&destination=${destination}` +
    (waypoints ? `&waypoints=${encodeURIComponent(waypoints)}` : "") + "&travelmode=transit";
}

// ------------------------------------------------------------------ booking: hotel offers + the whole trip
function modal(html) {
  closeModal();
  const wrap = document.createElement("div");
  wrap.className = "modal-wrap";
  wrap.innerHTML = `<div class="modal" role="dialog" aria-modal="true"><button class="icon-btn modal-x" type="button" aria-label="${t("close")}">${icon("x")}</button>${html}</div>`;
  wrap.addEventListener("click", (e) => { if (e.target === wrap || e.target.closest(".modal-x")) closeModal(); });
  document.body.appendChild(wrap);
  document.addEventListener("keydown", escClose);
  return wrap.querySelector(".modal");
}
function escClose(e) { if (e.key === "Escape") closeModal(); }
function closeModal() {
  document.querySelectorAll(".modal-wrap").forEach((m) => m.remove());
  document.removeEventListener("keydown", escClose);
}

async function openOffers(hotelId) {
  if (state.busy) return addMessage("assistant", t("busyWait"));  // the plan shown may not be saved yet
  const box = modal(`<div class="offers-loading"><div class="spinner"></div>${t("loadingOffers")}</div>`);
  let d;
  try {
    const res = await fetch(`/api/trips/${state.trip.trip_id}/hotel-offers?hotel_id=${encodeURIComponent(hotelId)}`);
    if (!res.ok) throw new Error(await res.text());
    d = await res.json();
  } catch (err) {
    console.error(err);
    box.innerHTML += `<p class="muted">${t("noOffers")}</p>`;
    box.querySelector(".offers-loading")?.remove();
    return;
  }
  const cur = d.currency;
  const gallery = (d.images || []).slice(0, 6).map((u) => `<div style="background-image:url('${esc(u)}')"></div>`).join("");
  const rows = d.offers.map((o) => `<a class="offer ${o.matches_plan ? "match" : ""}" href="${safeUrl(o.link)}" target="_blank" rel="noopener">
      ${o.logo ? `<img src="${esc(o.logo)}" alt="" loading="lazy">` : `<span class="logo-ph">${icon("bed")}</span>`}
      <div class="o-src"><b>${esc(o.source)}</b>
        <div class="o-tags">${o.matches_plan ? `<span class="badge ok">${t("matchesPlan")}</span>` : ""}${o.official ? `<span class="badge info">${t("official")}</span>` : ""}${o.free_cancellation ? `<span class="badge ok">${t("freeCancel")}</span>` : ""}</div></div>
      <div class="o-price"><b>${money(o.rate_per_night, cur)}</b><small>${t("perNight").trim()}</small><em>${money(o.total, cur)} ${t("totalNights", d.nights)}</em></div>
      <span class="o-cta">${t("bookOn")} ${icon("link")}</span></a>`).join("");
  box.innerHTML = `<button class="icon-btn modal-x" type="button" aria-label="${t("close")}">${icon("x")}</button>
    ${gallery ? `<div class="gallery">${gallery}</div>` : ""}
    <div class="modal-body">
      <p class="eyebrow">${t("offersTitle")}</p><h3>${esc(d.hotel)}</h3>
      <p class="muted">${esc(d.city)} · ${fmtDate(d.check_in)} → ${fmtDate(d.check_out)} · ${t("nights", d.nights)} · ${t("travellers", d.adults)}</p>
      ${rows ? `<div class="offers">${rows}</div><p class="muted small">${t("offersNote")}</p>` : `<p class="muted">${t("noOffers")}</p>`}
      <div class="modal-links"><a class="btn" href="${safeUrl(d.google_hotels)}" target="_blank" rel="noopener">${icon("globe")}${t("compareGoogle")}</a>
        ${d.hotel_website ? `<a class="btn ghost" href="${safeUrl(d.hotel_website)}" target="_blank" rel="noopener">${icon("link")}${t("hotelSite")}</a>` : ""}</div>
    </div>`;
}

function openBooking() {
  const trip = state.trip, c = trip.trip_contract, plan = trip.plans[trip.selected_mode];
  const legs = (plan.legs && plan.legs.length ? plan.legs : [plan.outbound_flight, plan.return_flight]).filter(Boolean);
  const hotels = isMulti(plan) ? plan.stops.filter((s) => s.hotel).map((s) => ({ h: s.hotel, label: s.name, nights: s.nights }))
    : plan.hotel ? [{ h: plan.hotel, label: c.destination_name, nights: Math.round((new Date(c.end_date) - new Date(c.start_date)) / 86400000) }] : [];
  const flightRows = legs.map((f, i) => `<div class="bk-row"><span class="bk-n">${i + 1}</span>
      <div><b>${esc(f.origin)} → ${esc(f.destination)}</b><small>${esc(f.airline)} ${esc(f.flight_number)} · ${fmtDate(f.depart_at.slice(0, 10))} ${f.depart_at.slice(11, 16)}</small></div>
      <div class="bk-price">${costLabel(f.price_per_person)}<small>${t("perPerson").trim()}</small></div>
      ${f.booking_url ? `<a class="btn" href="${safeUrl(f.booking_url)}" target="_blank" rel="noopener">${t("book")}</a>` : `<span class="muted small">${t("bookLocally")}</span>`}</div>`).join("");
  const hotelRows = hotels.map(({ h, label, nights }, i) => `<div class="bk-row"><span class="bk-n">${legs.length + i + 1}</span>
      <div><b>${esc(h.name)}</b><small>${esc(label)} · ${t("nights", nights)}</small></div>
      <div class="bk-price">${costLabel(h.price_per_night)}<small>${t("perNight").trim()}</small></div>
      <button class="btn primary" type="button" data-hotel="${esc(h.id)}">${t("seeOffers")}</button></div>`).join("");
  const box = modal(`<div class="modal-body">
      <p class="eyebrow">${t("bookTrip")}</p><h3>${esc(c.destination_name)}</h3>
      <p class="muted">${t("bookingSub")}</p>
      <div class="section-title">${t("flightsSec")}</div>${flightRows}
      <div class="section-title">${t("hotelsSec")}</div>${hotelRows}
      <div class="bk-total"><span>${t("tripTotal")}</span><b>${money(plan.budget.total, plan.budget.currency)}</b></div>
      <p class="muted small">${t("bookingNote")}</p></div>`);
  box.querySelectorAll("[data-hotel]").forEach((b) => b.addEventListener("click", () => openOffers(b.dataset.hotel)));
}

// ------------------------------------------------------------------ stay
function why(lines = []) {
  return `<ul>${lines.map((l) => l.startsWith("Trade-off:") ? `<li class="trade">${esc(l.replace("Trade-off: ", ""))}</li>` : `<li>${esc(l)}</li>`).join("")}</ul>`;
}
function flightCard(f, label, key, plan) {
  if (!f) return "";
  const dur = `${Math.floor(f.duration_minutes / 60)}h${String(f.duration_minutes % 60).padStart(2, "0")}`;
  return `<div class="card"><div class="k">${label}</div>
    <div class="row"><h3>${esc(f.airline)}</h3><div class="big">${costLabel(f.price_per_person)}<span class="muted" style="font-size:12px">${t("perPerson")}</span></div></div>
    <div class="flight-line"><div><div class="code">${esc(f.origin)}</div><div class="time">${f.depart_at.slice(11, 16)} · ${fmtDate(f.depart_at.slice(0, 10))}</div></div>
      <div class="bar"></div><div class="end"><div class="code">${esc(f.destination)}</div><div class="time">${f.arrive_at.slice(11, 16)}</div></div></div>
    <div class="muted" style="font-size:12.5px">${esc(f.flight_number)} · ${dur} · ${f.stops ? t("stop", f.stops) + (f.via ? ` ${t("via")} ` + esc(f.via) : "") : t("direct")}${f.carbon_kg ? ` · ${f.carbon_kg} kg CO₂` : ""}</div>
    ${f.segments?.length > 1 ? `<div class="segments">${f.segments.map(esc).join("<br>")}</div>` : ""}
    <div class="segments">${esc(f.baggage)}</div>
    ${why(plan.explanations[key])}
    ${f.booking_url ? `<a class="link" href="${safeUrl(f.booking_url)}" target="_blank" rel="noopener">${icon("link")}${t("bookFlights")}</a>` : ""}</div>`;
}
function groundCard(f, label) {
  const dur = `${Math.floor(f.duration_minutes / 60)}h${String(f.duration_minutes % 60).padStart(2, "0")}`;
  return `<div class="card leg-card ground"><div class="k">${label}</div>
    <div class="row"><h3>${icon(LEG_MODE_ICON[f.mode])} ${esc(f.airline)}</h3><div class="big">${costLabel(f.price_per_person)}<span class="muted" style="font-size:12px">${t("perPerson")}</span></div></div>
    <div class="flight-line"><div><div class="code city">${esc(f.origin)}</div><div class="time">${f.depart_at.slice(11, 16)} · ${fmtDate(f.depart_at.slice(0, 10))}</div></div>
      <div class="bar"></div><div class="end"><div class="code city">${esc(f.destination)}</div><div class="time">${f.arrive_at.slice(11, 16)}</div></div></div>
    <div class="muted" style="font-size:12.5px">${dur} ${t("cityToCity")} · ${esc(f.metadata.provider)}</div>
    <div class="segments">${esc(f.metadata.notes || "")}</div></div>`;
}
function stay(plan) {
  if (isMulti(plan)) {
    const c = state.trip.trip_contract;
    const names = [c.origin_city, ...plan.stops.map((s) => s.name), c.return_city || c.origin_city];
    const legs = plan.legs.map((f, i) => {
      const label = `${t("leg")} ${i + 1} · ${esc(names[i])} → ${esc(names[i + 1])}`;
      const key = i === 0 ? "outbound_flight" : i === plan.legs.length - 1 ? "return_flight" : "";
      return f.mode === "flight" ? flightCard(f, label, key, plan) : groundCard(f, label);
    }).join("");
    const hotels = plan.stops.map((s, i) => s.hotel
      ? hotelCard(s.hotel, `${i + 1} · ${esc(s.name)} · ${t("nights", s.nights)} · ${fmtDate(s.start_date)}–${fmtDate(s.end_date)}`, s.explanations)
      : `<div class="card"><div class="k">${esc(s.name)}</div><p class="muted">${t("noHotel")}</p></div>`).join("");
    return `<div class="section-title">${t("yourJourney")}</div><div class="grid2">${legs}</div>
      <div class="section-title">${t("whereSleep")}</div><div class="grid2">${hotels}</div>`;
  }
  const h = plan.hotel;
  const trip = state.trip;
  const hotel = h ? hotelCard(h, `${t("hotel")} · ${esc(h.neighborhood)}`, plan.explanations.hotel, true) : "";
  const alts = (plan.alternatives.hotels || []).map((id) => trip.research.hotels.find((x) => x.id === id)).filter(Boolean)
    .map((x) => `<tr><td>${esc(x.name)}</td><td>${x.rating}/5</td><td>${esc(x.neighborhood)}</td><td>${costLabel(x.price_per_night)}</td></tr>`).join("");
  const th = t("th");
  return `<div class="grid2">${flightCard(plan.outbound_flight, t("outbound"), "outbound_flight", plan)}${flightCard(plan.return_flight, t("return"), "return_flight", plan)}${hotel}</div>
    ${alts ? `<div class="section-title">${t("otherHotels")}</div><table><tr><th>${th.hotel}</th><th>${th.rating}</th><th>${th.location}</th><th>${th.night}</th></tr>${alts}</table>` : ""}`;
}
/** What real guests say, distilled by the review-analyst agent: verdict, aspect scores, pros and cons. */
function guestInsights(ri) {
  const ar = getLang() === "ar";
  const pick = (en, arr) => (ar && arr?.length ? arr : en) || [];
  const aspects = Object.entries(ri.aspects || {}).sort((a, b) => b[1] - a[1]);
  return `<div class="guests">
    <div class="g-head"><span>✨ ${t("guestsSay")}</span><small>${t("fromReviews", ri.reviews_read)}</small></div>
    <p class="g-sum">${esc(ar && ri.summary_ar ? ri.summary_ar : ri.summary)}</p>
    ${aspects.length ? `<div class="g-asp">${aspects.map(([k, v]) => `<div><span>${esc(t(`aspect.${k}`).startsWith("aspect.") ? k : t(`aspect.${k}`))}</span>
      <i><b style="width:${(v / 5) * 100}%" class="${v >= 4 ? "hi" : v >= 3 ? "mid" : "lo"}"></b></i><em>${v.toFixed(1)}</em></div>`).join("")}</div>` : ""}
    <div class="g-pc">${pick(ri.pros, ri.pros_ar).map((x) => `<span class="pro">＋ ${esc(x)}</span>`).join("")}
      ${pick(ri.cons, ri.cons_ar).map((x) => `<span class="con">－ ${esc(x)}</span>`).join("")}</div></div>`;
}
function hotelCard(h, label, explanations, wide = false) {
  const pics = (h.images || []).slice(0, 4);
  const gallery = pics.length > 1
    ? `<div class="hotel-gallery">${pics.map((u) => `<div style="background-image:url('${esc(u)}')"></div>`).join("")}</div>`
    : pics.length ? `<img class="hotel-img" src="${esc(pics[0])}" alt="${esc(h.name)}" loading="lazy">` : "";
  return `<div class="card hotel-card"${wide ? ' style="grid-column:1/-1"' : ""}>${gallery}
    <div class="k">${label}</div>
    <div class="row"><h3>${esc(h.name)}</h3><div class="big">${costLabel(h.price_per_night)}<span class="muted" style="font-size:12px">${t("perNight")}</span></div></div>
    <div class="tags" style="margin-top:6px">${h.stars ? `<span class="tag">${"★".repeat(h.stars)}</span>` : ""}<span class="tag">${h.rating}/5 · ${h.reviews_count.toLocaleString(locale())} ${t("reviews")}</span>
      <span class="tag">${h.breakfast_included ? t("breakfastYes") : t("breakfastNo")}</span><span class="tag">${esc(h.cancellation_policy)}</span>
      <span class="tag">${t("noise")}: ${esc(h.noise_level)}</span>${h.total_price ? `<span class="tag">${t("stayTotal")} ${costLabel(h.total_price)}</span>` : ""}</div>
    ${h.review_insights ? guestInsights(h.review_insights)
      : h.noise_evidence?.length ? `<details class="t-more"><summary>${t("guestsSaid")}</summary>“${esc(h.noise_evidence[0].slice(0, 320))}”</details>` : ""}
    ${why(explanations)}
    <div class="card-actions"><button class="btn primary" type="button" data-offers="${esc(h.id)}">${icon("bed")}${t("bookHotel")}</button>
      <a class="link" href="https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(h.name)}" target="_blank" rel="noopener">${icon("pin")}${t("mapsLink")}</a></div></div>`;
}

// ------------------------------------------------------------------ budget
const BUDGET_COLORS = { flights: "#9b8cff", hotel: "#3de0d0", food: "#ffb454", activities: "#ff6b8b", transport: "#36b7ff", buffer: "#5f6f8f" };
function budget(plan) {
  const b = plan.budget;
  const parts = Object.keys(BUDGET_COLORS).map((k) => [k, b[k]]).filter(([, v]) => v > 0);
  const R = 78, C = 2 * Math.PI * R;
  let off = 0;
  const arcs = parts.map(([k, v]) => {
    const len = (v / Math.max(b.total, 1)) * C;
    const s = `<circle cx="100" cy="100" r="${R}" stroke="${BUDGET_COLORS[k]}" stroke-dasharray="0 ${C}" data-dash="${Math.max(len - 2, 0)} ${C}" stroke-dashoffset="${-off}"/>`;
    off += len;
    return s;
  }).join("");
  const pct = Math.min(100, (b.total / b.limit) * 100);
  const days = Object.entries(b.daily_spending);
  const max = Math.max(...days.map(([, v]) => v), 1);
  const step = Math.max(50, Math.round(state.trip.trip_contract.budget.amount / 40 / 50) * 50);
  const usdRate = b.currency !== "USD" && state.trip.research?.fx_rates?.USD;  // 1 USD in the trip's currency
  const curs = CURRENCIES.includes(b.currency) ? CURRENCIES : [b.currency, ...CURRENCIES];
  return `<div class="cur-switch"><label>${t("pricesIn")} <select id="curSel" aria-label="${t("pricesIn")}">${curs.map((c) =>
      `<option${c === b.currency ? " selected" : ""}>${c}</option>`).join("")}</select></label>
      ${usdRate ? `<span class="muted">≈ ${money(b.total / usdRate, "USD")}</span>` : ""}</div>
    <div class="budget-top"><div class="donut"><svg viewBox="0 0 200 200">${arcs}</svg>
      <div class="center"><div><b>${money(b.total, b.currency)}</b><span>${t("of")} ${money(b.limit, b.currency)}</span></div></div></div>
    <div class="legend">${parts.map(([k, v]) => `<div><i style="background:${BUDGET_COLORS[k]}"></i><span>${t("cat")[k]}</span><b>${money(v, b.currency)}</b></div>`).join("")}</div></div>
    <div class="meter"><i class="${b.remaining < 0 ? "over" : ""}" style="width:${pct}%"></i></div>
    <div class="muted" style="font-size:13px">${b.remaining >= 0 ? `<span class="badge ok">${money(b.remaining, b.currency)} ${t("left")}</span>` : `<span class="badge bad">${money(-b.remaining, b.currency)} ${t("over")}</span>`}</div>
    ${certaintyBar(plan)}
    <div class="section-title">${t("perDay")}</div>
    <div class="bars">${days.map(([dt, v], i) => `<div><i style="height:${(v / max) * 100}%;animation-delay:${i * 60}ms" title="${money(v, b.currency)}"></i><span>${fmtDate(dt, { day: "numeric", month: "short" })}</span></div>`).join("")}</div>
    <div class="card whatif"><div class="k">${t("whatIf")}</div><h3>${t("changeBudget")}</h3>
      <div class="row"><input type="range" id="wiRange" min="${-step * 10}" max="${step * 10}" step="${step}" value="0" aria-label="${t("changeBudget")}"><b id="wiLabel">±0</b>
      <button class="btn" id="wiRun" type="button">${t("compare")}</button></div>
      <div id="wiOut" class="muted" style="font-size:13px;margin-top:8px">${t("whatIfNote")}</div></div>
    ${plan.repair_log.length ? `<div class="section-title">${t("repairs")}</div><ul class="muted" style="font-size:13px">${plan.repair_log.slice(-8).map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}`;
}
/** The share of the total that rests on published prices vs estimates. */
function certaintyBar(plan) {
  const c = priceCertainty(plan);
  const total = c.verified + c.calculated + c.ai + c.estimated;
  if (!total) return "";
  const pct = (v) => Math.round((v / total) * 100);
  const cur = userCur();
  const part = (k, cls, label) => c[k] ? `<span><i class="${cls}"></i>${label} ${pct(c[k])}% · ${money(c[k], cur)}</span>` : "";
  return `<div class="certainty"><div class="k">${t("certaintyTitle")}</div>
    <div class="cbar"><i class="v" style="width:${pct(c.verified)}%"></i><i class="c" style="width:${pct(c.calculated)}%"></i><i class="a" style="width:${pct(c.ai)}%"></i><i class="e" style="width:${pct(c.estimated)}%"></i></div>
    <div class="clegend">${part("verified", "v", t("cVerified"))}${part("calculated", "c", t("cCalculated"))}${part("ai", "a", t("cAI"))}${part("estimated", "e", t("cEstimated"))}</div>
    <p class="muted">${t("certaintyNote")}</p></div>`;
}
function wireWhatIf() {
  requestAnimationFrame(() => $("panel").querySelectorAll(".donut circle").forEach((c) => c.setAttribute("stroke-dasharray", c.dataset.dash)));
  const cur = userCur();
  const range = $("wiRange");
  range.addEventListener("input", () => { const v = +range.value; $("wiLabel").textContent = (v >= 0 ? "+" : "−") + money(Math.abs(v), cur); });
  const whatIf = async (body) => {
    const res = await fetch(`/api/trips/${state.trip.trip_id}/whatif`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (!res.ok) throw await httpError(res);
    return res.json();
  };
  const fail = (err) => { $("wiOut").textContent = err.status === 429 ? t("errRate", err.retry || "60") : t("errWhatIf"); };
  $("wiRun").addEventListener("click", async () => {
    const delta = +range.value;
    if (!delta || state.busy) return;
    $("wiOut").textContent = t("replanning");
    setBusy(true, t("replanning"));
    let r;
    try { r = await whatIf({ budget_delta: delta }); } catch (err) { return fail(err); } finally { setBusy(false); }
    const m = state.trip.selected_mode, a = r.before?.[m], b = r.after?.[m];
    if (!a || !b) return fail({});
    $("wiOut").innerHTML = `<p><b>${t("mode")[m]}</b>: ${money(a.total, a.currency || cur)} → <b>${money(b.total, b.currency || cur)}</b> · ${t("tripScore")} ${a.score} → <b>${b.score}</b></p>
      <ul>${r.changes.map((c) => `<li>${esc(c)}</li>`).join("") || `<li>${t("noChanges")}</li>`}</ul>
      <button class="btn primary" id="wiApply" type="button">${t("applyBudget")}</button>`;
    $("wiApply").addEventListener("click", async () => {
      if (state.busy) return;
      setBusy(true, t("replanning"));
      try {
        await whatIf({ budget_delta: delta, apply: true });  // saves exactly the version compared above
        const res = await fetch(`/api/trips/${state.trip.trip_id}`);
        if (!res.ok) throw await httpError(res);
        const updated = await res.json();
        addMessage("assistant", t("budgetUpdated", money(updated.trip_contract.budget.amount, updated.trip_contract.budget.currency)));
        setTrip(updated);
      } catch (err) { fail(err); } finally { setBusy(false); }
    });
  });
}

// ------------------------------------------------------------------ checks
function radar(score) {
  const keys = ["budget_fit", "comfort", "food", "activities", "transportation", "personal_fit", "schedule_quality"];
  const labels = t("radar");
  const cx = 120, cy = 110, R = 80;
  const pt = (i, v) => { const a = (Math.PI * 2 * i) / keys.length - Math.PI / 2; return [cx + Math.cos(a) * R * v, cy + Math.sin(a) * R * v]; };
  const grid = [0.25, 0.5, 0.75, 1].map((s) => `<polygon points="${keys.map((_, i) => pt(i, s).join(",")).join(" ")}" fill="none" stroke="rgba(160,190,255,.12)"/>`).join("");
  const shape = keys.map((k, i) => pt(i, score[k] / 100).join(",")).join(" ");
  const text = labels.map((l, i) => { const [x, y] = pt(i, 1.2); return `<text x="${x}" y="${y}" text-anchor="middle" dominant-baseline="middle">${l}</text>`; }).join("");
  return `<svg class="radar" viewBox="0 0 240 220" style="width:240px;height:220px">${grid}<polygon class="shape" points="${shape}"/>${text}</svg>`;
}
/** The critic agent's expert review of the plan: verdict, what it already improved, and open ideas (one tap to apply). */
function expertReview() {
  const c = state.trip.metadata?.critique;
  if (!c) return "";
  const ar = getLang() === "ar";
  const issues = c.issues || [];
  const other = c.mode && c.mode !== state.trip.selected_mode;
  return `<div class="card review">
    <div class="rv-head">${ring(c.quality, 58)}<div><div class="k">✨ ${t("expertReview")}</div>
      <p>${esc(ar && c.verdict_ar ? c.verdict_ar : c.verdict)}</p>
      ${other ? `<p class="muted" style="font-size:12.5px">${t("reviewOf", t("mode")[c.mode] || c.mode)}</p>` : ""}</div></div>
    ${issues.length ? `<ul class="rv-list">${issues.map((i) => `<li class="${i.applied ? "done" : "idea"}">
      <span class="rv-ic">${i.applied ? icon("check") : "💡"}</span>
      <div><b>${i.applied ? t("improved") : t("idea")}${i.day ? ` · ${t("day")} ${i.day}` : ""}</b>
        <span>${esc(ar && i.problem_ar ? i.problem_ar : i.problem)}</span>
        ${!i.applied && i.suggestion ? `<button class="chip ai" type="button" data-suggest="${esc(i.suggestion)}">✨ ${esc(i.suggestion)}</button>` : ""}</div></li>`).join("")}</ul>`
      : `<p class="muted" style="font-size:13px;margin:8px 0 0">${t("noIssues")}</p>`}</div>`;
}

// ------------------------------------------------------------------ the message's route through the system
// Every reply carries the path its message took (recorded by the server: telemetry + workflow._timed): each step of
// the agent graph, the tools and AI models each step called, and how long everything took. Drawn as a diagram.
const AGENT_ICON = { concierge: "🧭", critic: "🧐", strategist: "♟️", planner: "🧩" };
const KIND_LABEL = { thought: "💭", tool: "🛠️", observation: "👁️", decision: "⚖️", fix: "🔧", answer: "💬" };
const STAGE_ICON = { understand: "🧠", answer: "💬", check_requirements: "📋", ask: "❓", propose_route: "🗺️",
  apply_feedback: "🔧", research_setup: "🔎", research_flights: "✈️", research_hotels: "🏨", research_restaurants: "🍽️",
  research_activities: "🏛️", research_weather: "🌦️", collect: "💰", plan: "🧩", validate: "✅", repair: "🛠️",
  finalize: "🏁", critic: "🧐", respond: "✍️" };
// The research branch each tool server belongs to (they run side by side, so time alone can't tell).
const BRANCH_OF = { flights: "research_flights", hotels: "research_hotels", places: "research_restaurants",
  activities: "research_activities", weather: "research_weather" };
const BRANCH_STEPS = new Set(Object.values(BRANCH_OF));
// Which steps' thinking each agent's trace belongs under.
const TRACE_AT = { concierge: "understand", critic: "critic", strategist: "plan", planner: "plan" };
const secs = (ms) => `${(ms / 1000).toFixed(ms < 10000 ? 1 : 0)}s`;

/** A "how I answered" button under a reply (only when the server recorded the turn's path). */
const lastReply = () => [...document.querySelectorAll("#messages .msg.assistant")].pop();
function pathButton(after, meta) {
  if (!after || !meta?.turn_path?.nodes?.length) return;
  const b = document.createElement("button");
  b.type = "button";
  b.className = "path-btn";
  b.innerHTML = `🧭 ${esc(t("pathBtn"))} <span>${secs(meta.turn_path.total_ms)}</span>`;
  b.addEventListener("click", () => openPath(meta));
  after.after(b);
}

function openPath(meta) {
  const p = meta.turn_path;
  const nodes = p.nodes.map((n) => ({ ...n, start: n.end - n.ms, tools: [], llm: [], steps: [] }));
  // Each tool / model call belongs to the step that was running when it finished (a research branch by its server).
  const owner = (x, server) => {
    const live = nodes.filter((n) => x.end >= n.start - 30 && x.end <= n.end + 30);
    return (server && live.find((n) => n.name === BRANCH_OF[server])) || live.find((n) => !BRANCH_STEPS.has(n.name)) || live[0];
  };
  p.tools.forEach((x) => owner(x, x.name.split(".")[0])?.tools.push(x));
  p.llm.forEach((x) => owner(x)?.llm.push(x));
  (meta.agent_trace || []).forEach((s) => {
    const at = TRACE_AT[s.agent];
    const n = at && [...nodes].reverse().find((x) => x.name === at);
    if (n) n.steps.push(s);
  });
  const total = Math.max(p.total_ms, 1);
  const label = (n) => (t("stage")[n.name] || [n.name, ""]);

  const chips = (n) => {
    const byTool = {};
    n.tools.forEach((x) => { const k = x.name.split(".")[0]; byTool[k] = byTool[k] || { n: 0, ms: 0, bad: 0 };
      byTool[k].n += 1; byTool[k].ms = Math.max(byTool[k].ms, x.ms); byTool[k].bad += x.ok ? 0 : 1; });
    const tools = Object.entries(byTool).map(([k, v]) => `<span class="pc tool${v.bad ? " bad" : ""}">🛠️ ${esc(t("toolName")[k] || k)}${v.n > 1 ? ` ×${v.n}` : ""} · ${secs(v.ms)}</span>`);
    const models = n.llm.map((x) => `<span class="pc ai${x.ok ? "" : " bad"}">✨ ${esc(t("model")[x.what] || x.what)} · ${x.cached ? esc(t("pathMemory")) : secs(x.ms)}</span>`);
    return tools.length || models.length ? `<div class="p-chips">${models.join("")}${tools.join("")}</div>` : "";
  };
  const thinking = (n) => n.steps.length ? `<details class="p-think"><summary>${esc(t("pathAgent"))} (${n.steps.length})</summary>
      <ol class="trace">${n.steps.map((s) => `<li class="k-${s.kind}"><span class="tr-agent">${AGENT_ICON[s.agent] || "🤖"} ${esc(s.agent)}</span>
        <span class="tr-kind">${KIND_LABEL[s.kind] || ""} ${esc(s.kind)}</span><div class="tr-text" dir="auto">${esc(s.text)}</div></li>`).join("")}</ol></details>` : "";
  const card = (n, small) => `<div class="p-node${small ? " small" : ""}">
      <div class="p-head"><span class="p-ic">${STAGE_ICON[n.name] || "•"}</span><b>${esc(label(n)[0])}</b><span class="p-ms">${secs(n.ms)}</span></div>
      ${small ? "" : `<p>${esc(label(n)[1])}</p>`}${chips(n)}${thinking(n)}</div>`;
  // Consecutive research branches ran side by side: one row (and one stretch of the time bar, as long as the slowest).
  const rows = [];
  nodes.forEach((n) => {
    const branch = BRANCH_STEPS.has(n.name);
    const prev = rows[rows.length - 1];
    if (branch && prev && prev.parallel) prev.nodes.push(n);
    else rows.push({ parallel: branch, nodes: [n] });
  });
  const bar = rows.map((r) => {
    const ms = Math.max(...r.nodes.map((n) => n.ms));
    const name = r.parallel ? t("pathParallel") : label(r.nodes[0])[0];
    const ic = r.parallel ? "🔎" : STAGE_ICON[r.nodes[0].name] || "•";
    return ms >= total * 0.01 ? `<i style="flex:${ms}" title="${esc(name)} · ${secs(ms)}">${ms > total * 0.08 ? ic : ""}</i>` : "";
  }).join("");
  const u = meta.usage || {};
  modal(`<div class="path">
    <h3>${esc(t("pathTitle"))}</h3>
    <p class="muted">${esc(t("pathSum", secs(p.total_ms), p.llm.length, p.tools.length, u.serpapi_calls ?? 0))}</p>
    <div class="p-bar">${bar}</div>
    <div class="p-flow">${rows.map((r) => r.parallel
      ? `<div class="p-par"><small>${esc(t("pathParallel"))}</small><div>${r.nodes.map((n) => card(n, true)).join("")}</div></div>`
      : card(r.nodes[0], false)).join("")}</div></div>`);
}

function checks(plan) {
  const v = plan.validation;
  const s = plan.score;
  const ic = { PASS: "check", WARN: "alert", FAIL: "x" };
  return `${expertReview()}<div class="radar-wrap">${s ? radar(s) : ""}<div><div class="k" style="font-size:11.5px;letter-spacing:.1em;text-transform:uppercase;color:var(--faint)">${t("tripScore")}</div>
      <div style="display:flex;align-items:center;gap:14px;margin:6px 0">${ring(s ? s.total : 0, 80)}
      <div><b style="font:700 18px var(--display)">${v.result === "PASS" ? t("planChecked") : t("needsAttention")}</b><div class="muted" style="font-size:13px">${t("checksNote")}</div></div></div></div></div>
    <div class="checks">${v.checks.map((c, i) => `<div class="check" style="animation-delay:${i * 50}ms"><span class="ic ${c.status}">${icon(ic[c.status])}</span>
      <div><b>${t("checkNames")[c.name] || c.name}</b> <span class="badge ${c.status === "PASS" ? "ok" : c.status === "WARN" ? "warn" : "bad"}">${t("status")[c.status]}</span>
      ${c.messages.length ? `<ul>${c.messages.map((m) => `<li>${esc(m)}</li>`).join("")}</ul>` : ""}</div></div>`).join("")}</div>`;
}

// ------------------------------------------------------------------ weather / profile / sources
function weather() {
  const days = state.trip.research.weather;
  const src = days[0]?.metadata?.provider || "";
  return `<div class="wx">${days.map((w, i) => { const [ic, cls] = weatherIcon(w.condition); return `<div class="wx-card ${cls}" style="animation-delay:${i * 50}ms">
      <span>${fmtDate(w.date, { weekday: "short", day: "numeric" })}</span>${icon(ic)}<b>${Math.round(w.temp_max_c)}° <span style="display:inline;color:var(--muted);font-size:13px">${Math.round(w.temp_min_c)}°</span></b>
      <span>${esc(w.condition)}</span><span>${w.precipitation_probability}% ${t("rain")}</span>
      <span class="badge ${w.risk === "high" ? "bad" : w.risk === "medium" ? "warn" : "ok"}" style="margin-top:6px">${t("risk")[w.risk]}</span></div>`; }).join("")}</div>
    <p class="muted" style="font-size:12.5px;margin-top:14px">${t("source")}: ${esc(src)}. ${days.some((w) => w.metadata.confidence < 0.6) ? t("lastYear") : ""}</p>`;
}
function profile() {
  const p = state.trip.traveler_profile;
  const tags = (arr) => arr.length ? `<div class="tags">${arr.map((x) => `<span class="tag">${esc(x)}</span>`).join("")}</div>` : '<span class="muted">-</span>';
  const learned = Object.entries(p.learned || {});
  const L = t("prof");
  return `<dl class="kv">
    <dt>${L.pace}</dt><dd>${esc(p.travel_style.replace("_", " "))}</dd><dt>${L.interests}</dt><dd>${tags(p.activity_preferences)}</dd>
    <dt>${L.food}</dt><dd>${tags(p.food_preferences)}</dd><dt>${L.dietary}</dt><dd>${tags(p.dietary_restrictions)}</dd>
    <dt>${L.walking}</dt><dd>${esc(p.walking_tolerance)}</dd><dt>${L.daysStart}</dt><dd>${esc(p.preferred_wake_up_time)}</dd>
    <dt>${L.flights}</dt><dd>${esc(p.flight_preference)}${p.avoid_early_flights ? L.noEarly : ""}</dd>
    <dt>${L.noise}</dt><dd>${esc(p.noise_tolerance)}</dd><dt>${L.nightlife}</dt><dd>${esc(p.nightlife_interest)}</dd>
    <dt>${L.avoid}</dt><dd>${tags(p.avoid_categories)}</dd></dl>
    ${learned.length ? `<div class="section-title">${L.learned}</div><div class="tags">${learned.map(([k, v]) => `<span class="tag">${esc(k.replace(/_/g, " "))}: ${esc(v.value)} · ${Math.round(v.confidence * 100)}%</span>`).join("")}</div>
      <p class="muted" style="font-size:12.5px">${L.learnedNote}</p>` : ""}
    ${(state.trip.feedback || []).length ? `<div class="section-title">${L.feedback}</div><ul class="muted" style="font-size:13px">${state.trip.feedback.map((f) => `<li>“${esc(f.raw_text)}”</li>`).join("")}</ul>` : ""}`;
}
/** Where the prices come from: coverage of published entry / restaurant prices and the quoted fares. */
function priceSources(r) {
  const cov = r.price_coverage || {};
  const fs = r.fare_sources || {};
  // e.g. "Entry prices: 9/29 published (official site 4 · Wikivoyage 3 · Google 2) · AI estimate 17 · none 3"
  const row = (label, c) => {
    if (!c || !c.total) return "";
    const parts = [["official", t("psOfficial")], ["wikivoyage", "Wikivoyage"], ["google", "Google"]]
      .filter(([k]) => c[k]).map(([k, l]) => `${l} ${c[k]}`).join(" · ");
    const rest = [["ai", t("psAI")], ["reference", t("oldPrice")], ["none", t("psNone")]]
      .filter(([k]) => c[k]).map(([k, l]) => `${l} ${c[k]}`).join(" · ");
    return `<div><span>${label}</span><b>${c.verified}/${c.total}</b><small>${parts ? `(${parts})` : ""}${rest ? ` · ${rest}` : ""}</small></div>`;
  };
  const fare = (k, label) => `<li><b>${label}:</b> ${fs[k] ? esc(fs[k]) : `<span class="muted">${t("fareNA")}</span>`}</li>`;
  return `<div class="section-title">${t("pricesFrom")}</div>
    <div class="card price-src"><div class="ps-grid">${row(t("psSights"), cov.attractions)}${row(t("psFood"), cov.restaurants)}</div>
      <ul>${fare("transit", t("psTransit"))}${fare("taxi", t("psTaxi"))}${fs.airport ? fare("airport", t("psAirport")) : ""}</ul>
      <p class="muted">${t("pricesNote")}</p></div>`;
}
function sources(plan) {
  const r = state.trip.research;
  const seen = new Map();
  const add = (m) => { if (m) seen.set(m.source + "|" + m.provider, m); };
  [...r.flights_outbound.slice(0, 1), ...r.hotels.slice(0, 1), ...r.restaurants.slice(0, 1), ...r.attractions, ...r.weather, ...r.airport_transfers.slice(0, 1)].forEach((x) => add(x.metadata));
  add(r.fx_metadata);
  const items = plan.days.flatMap((d) => d.items).filter((i) => i.place_id);
  const places = items.map((i) => [...r.attractions, ...r.restaurants].find((p) => p.id === i.place_id)).filter(Boolean);
  const verified = places.filter((p) => p.hours_verified).length;
  return `<div class="grid2">
      <div class="card"><div class="k">${t("hoursVerified")}</div><div class="big">${places.length ? Math.round((verified / places.length) * 100) : 0}%</div><div class="muted" style="font-size:12.5px">${t("hoursNote")}</div></div>
      <div class="card"><div class="k">${t("priceLevel")}</div><div class="big">×${r.cost_factor}</div><div class="muted" style="font-size:12.5px">${t("priceLevelNote")}</div></div></div>
    ${priceSources(r)}
    <div class="section-title">${t("dataFrom")}</div>
    <table><tr><th>${t("th").source}</th><th>${t("th").updated}</th><th>${t("th").confidence}</th></tr>
    ${[...new Map([...seen.values()].map((m) => [m.provider, m])).values()].map((m) => `<tr><td>${esc(m.provider)}</td><td>${esc((m.retrieved_at || "").replace("T", " ").slice(0, 16))}</td><td>${Math.round(m.confidence * 100)}%</td></tr>`).join("")}</table>
    <p class="muted" style="font-size:12.5px">${t("fx")}: ${Object.entries(r.fx_rates).map(([k, v]) => `1 ${k} = ${(+v).toFixed(4)} ${userCur()}`).join(" · ")}</p>
    ${r.errors?.length ? `<div class="note">${t("someEstimates")}</div>` : ""}`;
}

// ------------------------------------------------------------------ trip ideas for a budget
const ideasState = { data: null, mode: "flex", occasion: null, interests: new Set(), stops: [] };
const OCCASIONS = [["solo", "🧍"], ["couple", "💑"], ["honeymoon", "💍"], ["family", "👨‍👩‍👧"], ["friends", "🎉"]];
const isoDay = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

/** Month list, flight-time list and preference chips (rebuilt on language change). */
function renderIdeaControls() {
  const month = $("ideaMonth").value, maxH = $("ideaMaxH").value;
  const now = new Date();
  const months = Array.from({ length: 12 }, (_, k) => new Date(now.getFullYear(), now.getMonth() + k, 1));
  $("ideaMonth").innerHTML = `<option value="">${t("anyTime")}</option>` + months.map((d) =>
    `<option value="${d.getMonth() + 1}">${d.toLocaleDateString(locale(), { month: "long", year: "numeric" })}</option>`).join("");
  $("ideaMonth").value = month;
  $("ideaMaxH").innerHTML = `<option value="">${t("anyFlight")}</option>` + [3, 5, 8, 12].map((h) => `<option value="${h}">${t("upToH", h)}</option>`).join("");
  $("ideaMaxH").value = maxH;
  $("occChips").innerHTML = OCCASIONS.map(([k, e]) =>
    `<button type="button" class="pchip${ideasState.occasion === k ? " on" : ""}" data-occ="${k}" aria-pressed="${ideasState.occasion === k}"><span>${e}</span>${t(`occ.${k}`)}</button>`).join("");
  $("intChips").innerHTML = INTERESTS.map(([k, e]) =>
    `<button type="button" class="pchip${ideasState.interests.has(k) ? " on" : ""}" data-int="${k}" aria-pressed="${ideasState.interests.has(k)}"><span>${e}</span>${t(`int.${k}`)}</button>`).join("");
  // How many preferences are set inside the folded "Personalise" panel.
  const n = (ideasState.occasion ? 1 : 0) + ideasState.interests.size + ($("ideaDirect").checked ? 1 : 0)
    + ($("ideaMaxH").value ? 1 : 0) + ($("ideaNotes").value.trim() ? 1 : 0);
  $("refineCount").textContent = n ? String(n) : "";
  const today = isoDay(new Date(Date.now() + 86400000));
  $("ideaStart").min = today;
  $("ideaEnd").min = $("ideaStart").value || today;
}
function setWhenMode(mode) {
  ideasState.mode = mode;
  $("whenMode").querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.dataset.mode === mode));
  $("whenFlex").hidden = mode !== "flex";
  $("whenDates").hidden = mode !== "dates";
}
$("whenMode").addEventListener("click", (e) => { const b = e.target.closest("button[data-mode]"); if (b) setWhenMode(b.dataset.mode); });
$("occChips").addEventListener("click", (e) => {
  const b = e.target.closest("[data-occ]");
  if (!b) return;
  ideasState.occasion = ideasState.occasion === b.dataset.occ ? null : b.dataset.occ;  // single choice, click again to clear
  renderIdeaControls();
});
$("intChips").addEventListener("click", (e) => {
  const b = e.target.closest("[data-int]");
  if (!b) return;
  const k = b.dataset.int;
  ideasState.interests.has(k) ? ideasState.interests.delete(k) : ideasState.interests.add(k);
  renderIdeaControls();
});
for (const id of ["ideaDirect", "ideaMaxH", "ideaNotes"]) $(id).addEventListener("change", renderIdeaControls);

// ------------------------------------------------------------------ home: inspiration (optional shortcuts)
const VIBES = [
  { k: "beach", e: "🏖️", len: "week", interests: ["beach", "relax"] },
  { k: "city", e: "🏙️", len: "weekend", interests: ["culture", "food", "shopping"] },
  { k: "history", e: "🏛️", len: "week", interests: ["history", "culture"] },
  { k: "honeymoon", e: "💍", len: "week", occasion: "honeymoon", interests: ["relax", "beach", "food"] },
  { k: "family", e: "👨‍👩‍👧", len: "week", occasion: "family", interests: ["nature", "beach"] },
  { k: "snow", e: "⛷️", len: "week", interests: ["ski", "nature"] },
];
// Famous destinations. Photos come from the Wikipedia article in `wiki` - chosen (and checked) so its lead image is a
// real photo: the "Santorini" and "Maldives" articles lead with a map and a flag, so they use Oia and a resort page.
const DESTS = [
  { name: "Istanbul", wiki: "Istanbul", months: [4, 5, 9, 10] }, { name: "Paris", wiki: "Paris", months: [4, 5, 6, 9] },
  { name: "Rome", wiki: "Rome", months: [4, 5, 9, 10] }, { name: "Dubai", wiki: "Dubai", months: [11, 12, 1, 2, 3] },
  { name: "Santorini", wiki: "Oia,_Greece", months: [5, 6, 9] }, { name: "Barcelona", wiki: "Barcelona", months: [5, 6, 9] },
  { name: "Marrakesh", wiki: "Marrakesh", months: [3, 4, 10, 11] }, { name: "Maldives", wiki: "Tourism_in_the_Maldives", months: [1, 2, 3, 4] },
  { name: "Tokyo", wiki: "Tokyo", months: [3, 4, 10, 11] }, { name: "Sharm El Sheikh", wiki: "Sharm_El_Sheikh", months: [10, 11, 3, 4] },
];
const HOW = [["chat", "howChat"], ["search", "howReal"], ["sparkle", "howReview"], ["link", "howBook"]];

async function wikiImage(title) {
  const key = `wikiimg2:${title}`;
  try { const c = localStorage.getItem(key); if (c) return c; } catch (_) { /* storage unavailable */ }
  try {
    const r = await fetch(`https://en.wikipedia.org/api/rest_v1/page/summary/${encodeURIComponent(title)}`);
    const j = await r.json();
    let src = (j.thumbnail || j.originalimage || {}).source || "";
    if (!/\.jpe?g(\?|$)/i.test(src)) src = "";  // photos only - never a map, flag or logo (those are SVG / PNG)
    try { if (src) localStorage.setItem(key, src); } catch (_) { /* storage unavailable */ }
    return src;
  } catch (_) { return ""; }
}

function renderHome() {
  $("vibes").innerHTML = VIBES.map((v) => `<button class="vibe" type="button" data-vibe="${v.k}">
      <span class="v-emoji">${v.e}</span><b>${t(`vibe.${v.k}`)}</b><small>${t(`vibeSub.${v.k}`)}</small></button>`).join("");
  const month = (m) => new Date(2026, m - 1, 1).toLocaleDateString(locale(), { month: "short" });
  $("dests").innerHTML = DESTS.map((d) => `<button class="dest" type="button" data-dest="${esc(d.name)}">
      <span class="d-img" data-wiki="${esc(d.wiki)}"></span>
      <span class="d-body"><b>${esc(placeLabel(d.name))}</b><small>${t("bestTime")}: ${d.months.map(month).join(" · ")}</small></span></button>`).join("");
  $("howSteps").innerHTML = HOW.map(([ic, k], i) => `<div class="how-step"><span class="hs-n">${i + 1}</span>${icon(ic)}
      <b>${t(`${k}.t`)}</b><p>${t(`${k}.p`)}</p></div>`).join("");
  $("dests").querySelectorAll("[data-wiki]").forEach(async (el) => {
    const src = await wikiImage(el.dataset.wiki);
    if (src) el.style.backgroundImage = `url('${src.replace(/'/g, "%27")}')`;
  });
}

$("vibes").addEventListener("click", (e) => {
  const b = e.target.closest("[data-vibe]");
  if (!b) return;
  const v = VIBES.find((x) => x.k === b.dataset.vibe);
  // A feeling, no place yet: the form opens with "suggest for me" and the vibe's interests already picked.
  openWizard({ where: "any", when: "flex", len: v.len, occasion: v.occasion || null, interests: new Set(v.interests) });
});
$("dests").addEventListener("click", (e) => {
  const b = e.target.closest("[data-dest]");
  if (!b) return;
  // Exactly the place that was tapped (a fresh start) - more cities can be added inside the form.
  logActivity("view", b.dataset.dest);
  openWizard({ where: "place", stops: [b.dataset.dest], step: 1 });
});

// ------------------------------------------------------------------ home: two ways to start
// 1) Chat: write the trip in your own words -> the conversation opens and Dalili takes it from there.
function renderExamples() {
  $("examples").innerHTML = t("examples").map((x) => `<button type="button" class="ex">${esc(x)}</button>`).join("");
}
$("examples").addEventListener("click", (e) => {
  const b = e.target.closest(".ex");
  if (!b) return;
  setText($("qcInput"), b.textContent);
  $("qcInput").focus();
});
$("quickChat").addEventListener("submit", (e) => {
  e.preventDefault();
  if (state.busy) return;
  const text = $("qcInput").value.trim();
  if (!text) { $("qcInput").focus(); return; }
  setText($("qcInput"), "");
  send(text);
});
wireTextBox($("qcInput"), $("quickChat"), 160);

/** A message box that grows with its text (long requests stay readable) and sends on Enter (Shift+Enter: new line). */
function wireTextBox(box, form, max) {
  const grow = () => { box.style.height = "auto"; if (box.value) box.style.height = Math.min(box.scrollHeight + 2, max) + "px"; };
  box.addEventListener("input", grow);
  box.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); form.requestSubmit(); }
  });
  box.grow = grow;
}
function setText(box, text) {
  box.value = text;
  box.grow?.();
}

// 2) The quick form: one question per step. It fills the (hidden) detailed form, then runs the same search /
//    planning logic, so both ways end in exactly the same place.
const WIZ_STEPS = 4;
const PICKS = ["Istanbul", "Dubai", "Paris", "Rome", "Sharm El Sheikh", "Barcelona"];
const wiz = { step: 1, where: "place", when: "dates", len: "week", pax: 1, stops: [], occasion: null, interests: new Set() };

/** Open the quick form. `fresh` (the default) starts a new trip - only the origin and budget are kept; reopening it to
 *  fix a problem (formProblem) keeps every answer. */
function openWizard(prefill = {}, fresh = true) {
  if (fresh) {
    Object.assign(wiz, { where: "place", when: "dates", len: "week", stops: [], occasion: null, interests: new Set() });
    $("wTo").value = ""; $("wNotes").value = ""; $("wDirect").checked = false;
  }
  Object.assign(wiz, prefill);
  // Keep what the traveller already gave us (origin, budget) between openings.
  if (!$("wFrom").value) $("wFrom").value = $("ideaFrom").value;
  if (!$("wBudget").value && +$("ideaBudget").value) $("wBudget").value = $("ideaBudget").value;
  $("wMonth").innerHTML = $("ideaMonth").innerHTML;
  $("wizErr").hidden = true;
  $("wizard").hidden = false;
  document.addEventListener("keydown", wizKeys);
  showStep(prefill.step || 1);
}
function closeWizard() {
  $("wizard").hidden = true;
  document.removeEventListener("keydown", wizKeys);
}
function wizKeys(e) {
  if (e.key === "Escape") closeWizard();
  if (e.key === "Enter" && e.target.id !== "wTo" && e.target.tagName !== "BUTTON" && !e.target.closest(".wiz-nav")) {
    e.preventDefault();
    if (wiz.step < WIZ_STEPS) nextStep();
  }
}
$("openWizard").addEventListener("click", () => openWizard({}));
$("wizClose").addEventListener("click", closeWizard);
$("wizard").addEventListener("click", (e) => { if (e.target.id === "wizard") closeWizard(); });

function showStep(n) {
  wiz.step = Math.max(1, Math.min(WIZ_STEPS, n));
  document.querySelectorAll(".wiz-step").forEach((s) => { s.hidden = +s.dataset.step !== wiz.step; });
  renderWizard();
  const first = document.querySelector(`.wiz-step[data-step="${wiz.step}"] input:not([type=checkbox]), .wiz-step[data-step="${wiz.step}"] select`);
  if (first && window.innerWidth > 700) setTimeout(() => first.focus(), 60);
}
function renderWizard() {
  const labels = t("wSteps");
  $("wizSteps").innerHTML = labels.map((l, i) => `<button type="button" class="ws ${i + 1 === wiz.step ? "on" : i + 1 < wiz.step ? "done" : ""}"
      data-go="${i + 1}" ${i + 1 > wiz.step ? "disabled" : ""}><i>${i + 1 < wiz.step ? "✓" : i + 1}</i><span>${l}</span></button>`).join("");
  // 1. where
  $("wWhereMode").querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.dataset.v === wiz.where));
  $("wPlaceBox").hidden = wiz.where !== "place";
  $("wStops").innerHTML = wiz.stops.map((s, i) => `${i ? '<b class="tr-arrow">→</b>' : ""}<span class="w-stop">${esc(placeLabel(s))}<button type="button" data-rm="${i}" aria-label="${t("clear")}">×</button></span>`).join("")
    + (wiz.stops.length === 1 ? `<small class="w-hint">${t("wMoreCities")}</small>` : "");
  $("wPicks").innerHTML = `<small>${t("wPopular")}</small>` + PICKS.filter((p) => !wiz.stops.includes(p))
    .map((p) => `<button type="button" class="ex" data-pick="${esc(p)}">${esc(placeLabel(p))}</button>`).join("");
  // 2. when
  $("wWhenMode").querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.dataset.v === wiz.when));
  $("wDatesBox").hidden = wiz.when !== "dates";
  $("wFlexBox").hidden = wiz.when !== "flex";
  $("wLen").querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.dataset.v === wiz.len));
  const tomorrow = isoDay(new Date(Date.now() + 86400000));
  $("wStart").min = tomorrow; $("wEnd").min = $("wStart").value || tomorrow;
  // 3. who & budget
  $("wPax").textContent = wiz.pax;
  $("wOcc").innerHTML = OCCASIONS.map(([k, e]) => `<button type="button" class="pchip${wiz.occasion === k ? " on" : ""}" data-occ="${k}"><span>${e}</span>${t(`occ.${k}`)}</button>`).join("");
  // 4. loves + summary
  $("wInt").innerHTML = INTERESTS.map(([k, e]) => `<button type="button" class="pchip${wiz.interests.has(k) ? " on" : ""}" data-int="${k}"><span>${e}</span>${t(`int.${k}`)}</button>`).join("");
  $("wSummary").innerHTML = wiz.step === WIZ_STEPS ? wizSummary() : "";
  // navigation: Next, or the final action(s)
  $("wizBack").style.visibility = wiz.step > 1 ? "visible" : "hidden";
  const acts = wiz.step < WIZ_STEPS ? [["next", t("next"), true]]
    : wiz.where === "any" || !wiz.stops.length ? [["ideas", t("findTrips"), true]]
      : wiz.stops.length >= 2 ? [["route", t("planRoute"), true]]
        : [["ideas", t("comparePrices"), false], ["plan", t("planMyTrip"), true]];
  $("wizNext").innerHTML = acts.map(([a, l, p]) => `<button class="btn ${p ? "primary" : "ghost"}" type="button" data-act="${a}">${l}</button>`).join("");
}
/** The traveller's language for known places ("Rome" -> "روما"); the English name stays for the planner. */
function placeLabel(name) {
  const l = t(`dest.${name.replace(/ /g, "_")}`);
  return l.startsWith("dest.") ? name : l;
}
function wizSummary() {
  const where = wiz.where === "any" || !wiz.stops.length ? t("wAnywhere") : wiz.stops.map(placeLabel).join(" → ");
  const when = wiz.when === "dates" ? `${fmtDate($("wStart").value)} → ${fmtDate($("wEnd").value)}`
    : `${$("wMonth").selectedOptions[0]?.textContent || t("anyTime")} · ${t(wiz.len === "two_weeks" ? "twoWeeks" : wiz.len)}`;
  const budget = +$("wBudget").value ? money(+$("wBudget").value, $("wCur").value) : "";
  return `<b>${t("wReady")}</b><span>📍 ${esc(where)}</span><span>🛫 ${esc($("wFrom").value.trim())}</span><span>📅 ${esc(when)}</span>
    <span>👥 ${wiz.pax}</span><span>💰 ${budget}</span>`;
}

// step 1 - where
$("wWhereMode").addEventListener("click", (e) => { const b = e.target.closest("[data-v]"); if (b) { wiz.where = b.dataset.v; renderWizard(); } });
function wizAddStop(name) {
  for (const n of String(name).split(/[,،→]/).map((x) => x.trim()).filter(Boolean)) {
    if (wiz.stops.length < 6 && !wiz.stops.some((s) => s.toLowerCase() === n.toLowerCase())) wiz.stops.push(n);
  }
  $("wTo").value = "";
  renderWizard();
}
$("wToAdd").addEventListener("click", () => { wizAddStop($("wTo").value); $("wTo").focus(); });
$("wTo").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); if ($("wTo").value.trim()) wizAddStop($("wTo").value); else nextStep(); } });
$("wStops").addEventListener("click", (e) => { const b = e.target.closest("[data-rm]"); if (b) { wiz.stops.splice(+b.dataset.rm, 1); renderWizard(); } });
$("wPicks").addEventListener("click", (e) => { const b = e.target.closest("[data-pick]"); if (b) wizAddStop(b.dataset.pick); });
// step 2 - when
$("wWhenMode").addEventListener("click", (e) => { const b = e.target.closest("[data-v]"); if (b) { wiz.when = b.dataset.v; renderWizard(); } });
$("wLen").addEventListener("click", (e) => { const b = e.target.closest("[data-v]"); if (b) { wiz.len = b.dataset.v; renderWizard(); } });
$("wStart").addEventListener("change", () => {
  const s = $("wStart").value;
  if (s && (!$("wEnd").value || $("wEnd").value <= s)) { const d = new Date(s); d.setDate(d.getDate() + 7); $("wEnd").value = isoDay(d); }
  renderWizard();
});
// step 3 - who & budget
$("wPaxMinus").addEventListener("click", () => { wiz.pax = Math.max(1, wiz.pax - 1); renderWizard(); });
$("wPaxPlus").addEventListener("click", () => { wiz.pax = Math.min(9, wiz.pax + 1); renderWizard(); });
$("wOcc").addEventListener("click", (e) => {
  const b = e.target.closest("[data-occ]");
  if (!b) return;
  wiz.occasion = wiz.occasion === b.dataset.occ ? null : b.dataset.occ;
  if (wiz.occasion === "couple" || wiz.occasion === "honeymoon") wiz.pax = Math.max(wiz.pax, 2);
  renderWizard();
});
// step 4 - loves
$("wInt").addEventListener("click", (e) => {
  const b = e.target.closest("[data-int]");
  if (!b) return;
  wiz.interests.has(b.dataset.int) ? wiz.interests.delete(b.dataset.int) : wiz.interests.add(b.dataset.int);
  renderWizard();
});
$("wizSteps").addEventListener("click", (e) => { const b = e.target.closest("[data-go]"); if (b && !b.disabled) showStep(+b.dataset.go); });
$("wizBack").addEventListener("click", () => showStep(wiz.step - 1));

/** Check the current step; the message says exactly what's missing. */
function wizCheck(step) {
  if (step === 1) {
    if ($("wTo").value.trim()) wizAddStop($("wTo").value);
    if (wiz.where === "place" && !wiz.stops.length) return [t("wErrWhere"), "wTo"];
    if (!$("wFrom").value.trim()) return [t("wErrFrom"), "wFrom"];
  }
  if (step === 2) {
    if (wiz.where === "place" && wiz.stops.length >= 2 && wiz.when !== "dates") return [t("multiDates"), "wStart"];
    if (wiz.when === "dates") {
      const s = $("wStart").value, en = $("wEnd").value;
      if (!s || !en || en <= s) return [t("datesErr"), "wStart"];
    }
  }
  if (step === 3 && !(+$("wBudget").value > 0)) return [t("budgetFirst"), "wBudget"];
  return null;
}
function nextStep() {
  const bad = wizCheck(wiz.step);
  $("wizErr").hidden = !bad;
  if (bad) { $("wizErr").textContent = bad[0]; $(bad[1])?.focus(); return; }
  showStep(wiz.step + 1);
}
$("wizNext").addEventListener("click", (e) => {
  const b = e.target.closest("[data-act]");
  if (!b) return;
  if (b.dataset.act === "next") return nextStep();
  if (state.busy) { $("wizErr").textContent = t("busyWait"); $("wizErr").hidden = false; return; }
  for (const s of [1, 2, 3]) {  // everything still valid (the traveller may have jumped back)
    const bad = wizCheck(s);
    if (bad) { showStep(s); $("wizErr").textContent = bad[0]; $("wizErr").hidden = false; return; }
  }
  wizApply();
  closeWizard();
  if (wiz.where === "place") wiz.stops.forEach((s) => logActivity("search", s));  // what the recommender learns from
  if (b.dataset.act === "route") planRouteFromForm(allStops());
  else if (b.dataset.act === "plan") { resetTrip(); send(t("planMsg", planPayload())); }  // the form is a new trip
  else loadIdeas();
});

/** Copy the answers into the detailed form that the search and planning logic read. */
function wizApply() {
  $("ideaFrom").value = $("wFrom").value.trim();
  $("ideaPax").value = wiz.pax;
  $("ideaBudget").value = $("wBudget").value;
  const cur = $("wCur").value;
  if (![...$("ideaCur").options].some((o) => o.value === cur)) $("ideaCur").add(new Option(cur, cur));
  $("ideaCur").value = cur;
  const places = wiz.where === "place" ? wiz.stops : [];
  ideasState.stops = places.length >= 2 ? places.map((n) => ({ name: n, nights: null })) : [];
  $("ideaTo").value = places.length === 1 ? places[0] : "";
  if (wiz.when === "dates") {
    setWhenMode("dates");
    $("ideaStart").value = $("wStart").value; $("ideaEnd").value = $("wEnd").value;
  } else {
    setWhenMode("flex");
    $("ideaMonth").value = $("wMonth").value;
    $("ideaLen").value = wiz.len;
  }
  ideasState.occasion = wiz.occasion;
  ideasState.interests = new Set(wiz.interests);
  $("ideaDirect").checked = $("wDirect").checked;
  $("ideaNotes").value = $("wNotes").value.trim();
  renderIdeaControls();
  renderRoute();
}
function planPayload() {
  const stops = allStops();
  return {
    dest: stops[0]?.name || "", origin: $("ideaFrom").value.trim(), travelers: +$("ideaPax").value || 1,
    budget: +$("ideaBudget").value || 0, currency: $("ideaCur").value,
    start: ideasState.mode === "dates" ? $("ideaStart").value : "", end: ideasState.mode === "dates" ? $("ideaEnd").value : "",
    month: ideasState.mode === "flex" ? $("ideaMonth").selectedOptions[0]?.textContent : "",
    len: $("ideaLen").selectedOptions[0]?.textContent,
    interests: [...ideasState.interests], occasion: ideasState.occasion, notes: $("ideaNotes").value.trim(),
  };
}
/** A problem found later (e.g. by the search): reopen the quick form on the step that needs fixing. */
function formProblem(msg, field) {
  const step = { ideaBudget: 3, ideaStart: 2, ideaEnd: 2 }[field] || 1;
  openWizard({ step }, false);
  $("wizErr").textContent = msg;
  $("wizErr").hidden = false;
}

// ------------------------------------------------------------------ several cities in "To" (multi-city route)
/** The route: cities added with Enter / "+" (in order), plus whatever is still typed in the field. */
function allStops() {
  const typed = $("ideaTo").value.trim();
  return [...ideasState.stops, ...(typed ? [{ name: typed, nights: null }] : [])];
}
function addStop(name) {
  for (const n of String(name).split(/[,،→]/).map((x) => x.trim()).filter(Boolean)) {
    if (ideasState.stops.length >= 6) break;
    if (!ideasState.stops.some((s) => s.name.toLowerCase() === n.toLowerCase())) ideasState.stops.push({ name: n, nights: null });
  }
  $("ideaTo").value = "";
  renderRoute();
}
function renderRoute() {
  const stops = ideasState.stops;
  $("ideaToAdd").hidden = !$("ideaTo").value.trim();
  $("toRoute").hidden = !stops.length;
  $("toRoute").innerHTML = stops.length ? `<span class="tr-lbl">${icon("route")}${t("yourRoute")}</span>
    ${stops.map((s, i) => `${i ? '<b class="tr-arrow">→</b>' : ""}<span class="tr-stop">
      <i>${i + 1}</i><span class="tr-name">${esc(s.name)}</span>
      <input type="number" min="1" max="30" class="tr-nights" data-i="${i}" value="${s.nights ?? ""}" placeholder="${t("nightsPh")}" aria-label="${t("nightsPh")}">
      ${i ? `<button type="button" class="tr-btn" data-move="${i}" title="${t("moveEarlier")}">‹</button>` : ""}
      <button type="button" class="tr-btn" data-del="${i}" title="${t("clear")}">×</button></span>`).join("")}
    <small class="tr-hint">${stops.length < 2 ? t("routeHint1") : t("routeHint2")}</small>` : "";
  const multi = allStops().length >= 2;
  $("ideasGo").querySelector("span").textContent = multi ? t("planRoute") : t("showIdeas");
  $("ideasGo").classList.toggle("multi", multi);
}
$("ideaTo").addEventListener("input", renderRoute);
$("ideaTo").addEventListener("keydown", (e) => {
  if ((e.key === "Enter" || e.key === ",") && $("ideaTo").value.trim()) { e.preventDefault(); addStop($("ideaTo").value); }
  else if (e.key === "Backspace" && !$("ideaTo").value && ideasState.stops.length) { ideasState.stops.pop(); renderRoute(); }
});
$("ideaToAdd").addEventListener("click", () => { addStop($("ideaTo").value); $("ideaTo").focus(); });
$("toRoute").addEventListener("click", (e) => {
  const del = e.target.closest("[data-del]"), mv = e.target.closest("[data-move]");
  if (del) ideasState.stops.splice(+del.dataset.del, 1);
  if (mv) { const i = +mv.dataset.move; [ideasState.stops[i - 1], ideasState.stops[i]] = [ideasState.stops[i], ideasState.stops[i - 1]]; }
  if (del || mv) renderRoute();
});
$("toRoute").addEventListener("change", (e) => {
  const inp = e.target.closest(".tr-nights");
  if (inp) ideasState.stops[+inp.dataset.i].nights = +inp.value > 0 ? Math.min(30, Math.round(+inp.value)) : null;
});

/** Two or more cities: not an ideas search - the planner builds the whole multi-city trip. */
function planRouteFromForm(stops) {
  const err = (msg, focus) => formProblem(msg, focus);
  $("ideasErr").hidden = true;
  if (!(+$("ideaBudget").value > 0)) return err(t("budgetFirst"), "ideaBudget");
  if (ideasState.mode !== "dates") { setWhenMode("dates"); return err(t("multiDates"), "ideaStart"); }
  const s = $("ideaStart").value, en = $("ideaEnd").value;
  if (!s || !en || en <= s) return err(t("datesErr"), "ideaStart");
  const total = Math.round((new Date(en) - new Date(s)) / 86400000);
  const given = stops.filter((x) => x.nights).length;
  if (given && given < stops.length) return err(t("nightsAllOrNone"));
  const sum = stops.reduce((a, x) => a + (x.nights || 0), 0);
  if (given && sum !== total) return err(t("nightsMismatch", sum, total));
  const d = { stops, origin: $("ideaFrom").value.trim(), start: s, end: en, travelers: +$("ideaPax").value || 1,
    budget: +$("ideaBudget").value, currency: $("ideaCur").value, occasion: ideasState.occasion,
    interests: [...ideasState.interests], notes: $("ideaNotes").value.trim(), direct: $("ideaDirect").checked };
  saveIdeasForm();
  resetTrip();  // the form always describes a new trip
  send(t("multiMsg", d));
}
function saveIdeasForm(extra = {}) {
  try {
    const f = JSON.parse(localStorage.getItem("ideasForm") || "{}");
    localStorage.setItem("ideasForm", JSON.stringify({ ...f, budget: +$("ideaBudget").value, currency: $("ideaCur").value,
      origin: $("ideaFrom").value.trim(), travelers: +$("ideaPax").value || 1, stops: ideasState.stops,
      start_date: $("ideaStart").value, end_date: $("ideaEnd").value, mode: ideasState.mode, ...extra }));
  } catch (_) { /* storage unavailable */ }
}
$("scrollHint").addEventListener("click", () => $("homeMore").scrollIntoView({ behavior: "smooth", block: "start" }));
$("ideaStart").addEventListener("change", () => {
  const s = $("ideaStart").value;
  $("ideaEnd").min = s;
  if (s && (!$("ideaEnd").value || $("ideaEnd").value <= s)) {  // suggest a week by default
    const d = new Date(s); d.setDate(d.getDate() + 7); $("ideaEnd").value = isoDay(d);
  }
});

async function loadIdeas(e) {
  e?.preventDefault();
  const stops = allStops();
  if (stops.length >= 2) return planRouteFromForm(stops);  // a multi-city route goes straight to the planner
  const budget = +$("ideaBudget").value;
  if (!budget) return formProblem(t("budgetFirst"), "ideaBudget");
  const body = { budget, currency: $("ideaCur").value, origin: $("ideaFrom").value.trim(), travelers: +$("ideaPax").value || 1,
    duration: $("ideaLen").value, month: +$("ideaMonth").value || null, interests: [...ideasState.interests],
    occasion: ideasState.occasion, direct_only: $("ideaDirect").checked, max_flight_hours: +$("ideaMaxH").value || null,
    notes: $("ideaNotes").value.trim(), lang: getLang(), destination: stops[0]?.name || "" };
  $("ideasErr").hidden = true;
  if (ideasState.mode === "dates") {
    const s = $("ideaStart").value, en = $("ideaEnd").value;
    if (!s || !en || en <= s) return formProblem(t("datesErr"), "ideaStart");
    Object.assign(body, { start_date: s, end_date: en, month: null });
  }
  try { localStorage.setItem("ideasForm", JSON.stringify({ ...body, mode: ideasState.mode, stops: ideasState.stops })); } catch (_) { /* storage unavailable */ }
  $("ideasGo").disabled = true;
  $("ideasNote").hidden = false;
  $("ideasNote").className = "ideas-note";
  $("ideasNote").textContent = t("ideasLoading");
  $("hero").classList.add("has-results");
  $("ideasGrid").innerHTML = Array.from({ length: 4 }, () => '<div class="idea skeleton"></div>').join("");
  $("ideasNote").scrollIntoView({ behavior: "smooth", block: "start" });  // results sit under the first screen
  try {
    const res = await fetch("/api/suggest", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (!res.ok) throw new Error(await res.text());
    ideasState.data = await res.json();
    renderIdeas();
  } catch (err) {
    console.error(err);
    $("ideasGrid").innerHTML = "";
    $("hero").classList.remove("has-results");
    $("ideasNote").className = "ideas-note bad";
    $("ideasNote").textContent = String(err.message).includes("destination") ? t("destError") : t("ideasError");
  } finally {
    $("ideasGo").disabled = false;
  }
}

function renderIdeas() {
  const d = ideasState.data;
  if (!d) return;
  const notes = [d.destination ? t("ideasTo", d.destination.name) : "",
    !d.all_fit ? t("ideasNone") : "", d.personal && d.all_fit ? t("rankedNote") : "",
    d.estimated ? t("ideasEstimated") : t("hotelTypical")].filter(Boolean);
  $("ideasNote").hidden = !notes.length;
  $("ideasNote").className = "ideas-note" + (d.all_fit ? "" : " warn");
  $("ideasNote").textContent = notes.join(" ");
  const fitBadge = (i) => i.fit === "comfortable" ? `<span class="idea-left ok">${money(i.left, d.currency)} ${t("leftFor")}</span>`
    : i.fit === "tight" ? `<span class="idea-left tight">${t("tightLeft", money(i.left, d.currency))}</span>`
      : `<span class="idea-left bad">${money(-i.left, d.currency)} ${t("overBy")}</span>`;
  $("hero").classList.toggle("has-results", d.ideas.length > 0);
  $("ideasGrid").innerHTML = d.ideas.map((i, k) => `<button class="idea fit-${i.fit}${i.target ? " target" : ""}" type="button" data-k="${k}" style="animation-delay:${k * 45}ms">
      <div class="idea-img" ${i.thumbnail ? `style="background-image:url('${esc(i.thumbnail)}')"` : ""}>
        ${i.score != null ? `<span class="idea-match" style="--m:${i.score}">${t("match", i.score)}</span>` : ""}
        ${fitBadge(i)}</div>
      <div class="idea-body">
        <div class="idea-name">${esc(i.name)}<small>${esc(i.country)}</small></div>
        ${i.why ? `<p class="idea-why">${esc(i.why)}</p>` : ""}
        ${i.taste_because?.city ? `<p class="idea-why taste">${t("likeYour", esc(i.taste_because.city))}</p>` : ""}
        ${i.tags?.length ? `<div class="idea-tags">${i.tags.map((x) => `<span>${esc(x)}</span>`).join("")}</div>` : ""}
        <div class="idea-dates">${i.start_date ? `${fmtDate(i.start_date)}${arrow()}${fmtDate(i.end_date)} · ` : ""}${t("nightsN", i.nights)}</div>
        ${i.flight_minutes ? `<div class="idea-dates">${t("flightH", i.flight_minutes)}${i.stops === 0 ? ` · ${t("nonstop")}` : i.stops ? ` · ${t("stop", i.stops)}` : ""}${i.airline ? ` · ${esc(i.airline)}` : ""}</div>` : ""}
        <div class="idea-prices"><span>${icon("plane")}${money(i.flight_price, d.currency)}</span>${i.hotel_price ? `<span>${icon("bed")}${money(i.hotel_price, d.currency)}${t("perNight")}</span>` : `<span class="muted">${icon("bed")}${t("hotelNotIncl")}</span>`}</div>
        <div class="idea-total"><span>${t("totalFH")}</span><b>${money(i.total, d.currency)}</b></div>
        <span class="idea-cta">${t("planIt")} →</span>
      </div></button>`).join("");
  $("ideasGrid").querySelectorAll(".idea").forEach((b) => {
    const idea = d.ideas[+b.dataset.k];
    tilt(b, 7);
    // Hover: preview the route on the globe.
    b.addEventListener("pointerenter", () => {
      if (idea.lat != null && !state.trip) globe.setJourney({ lat: d.origin.lat, lon: d.origin.lon, name: d.origin.name }, [{ lat: idea.lat, lon: idea.lon, name: idea.name }]);
    });
    b.addEventListener("click", () => {
      if (state.busy) return;
      resetTrip();  // an idea is a new trip
      send(t("ideaMsg", idea, d));
    });
  });
}
$("ideasForm").addEventListener("submit", loadIdeas);
$("bookTrip").addEventListener("click", openBooking);
$("ratePlan").addEventListener("click", openRating);

// ------------------------------------------------------------------ human evaluation (anonymous 1-5 ratings)
const RATE_DIMS = ["relevance", "personalization", "trust", "explanations", "itinerary", "usability", "confidence", "overall"];
function openRating() {
  if (!state.trip) return;
  const box = modal(`<div class="modal-body"><p class="eyebrow">${t("ratePlan")}</p><h3>${t("rateTitle")}</h3><p class="muted">${t("rateSub")}</p>
    <form class="rate-form" id="rateForm">${RATE_DIMS.map((d) => `<div class="rate-row"><span>${t("rate." + d)}</span>
      <div class="rate-scale" role="radiogroup" aria-label="${esc(t("rate." + d))}">${[1, 2, 3, 4, 5].map((v) =>
        `<label><input type="radio" name="${d}" value="${v}" required><b>${v}</b></label>`).join("")}</div></div>`).join("")}
      <textarea name="comment" maxlength="1000" dir="auto" placeholder="${esc(t("rateComment"))}"></textarea>
      <button class="btn primary" type="submit">${t("rateSend")}</button></form></div>`);
  box.querySelector("#rateForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    const ratings = Object.fromEntries(RATE_DIMS.map((d) => [d, +f.get(d)]));
    const res = await fetch("/api/evaluations", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ trip_id: state.trip.trip_id, ratings, comment: f.get("comment") || "" }) });
    box.querySelector(".modal-body").innerHTML = `<p class="rate-done">${res.ok ? t("rateThanks") : t("rateFailed")}</p>`;
    setTimeout(closeModal, 1600);
  });
}

// ------------------------------------------------------------------ chat open / close
function setChatOpen(open) {
  document.body.classList.toggle("chat-closed", !open);
  // On the home page the chat card is the way in; the floating button only helps once there's a conversation.
  const talking = !!state.tripId || $("messages").querySelectorAll(".msg.user").length > 0;
  $("chatFab").hidden = open || !talking;
  try { localStorage.setItem("chatOpen", open ? "1" : "0"); } catch (_) { /* storage unavailable */ }
  requestAnimationFrame(layoutGlobe);
}
function openChat() {
  if (document.body.classList.contains("chat-closed")) setChatOpen(true);
  setView("chat");
}
$("chatClose").addEventListener("click", () => { setChatOpen(false); setView("home"); });
$("chatFab").addEventListener("click", () => {
  setChatOpen(true);
  $("input").focus({ preventScroll: true });
});

// ------------------------------------------------------------------ phones: one screen at a time and a bottom bar
// Home, Chat and My trip are screens of the page (body[data-mview], styles.css); Events and Account are the pages that
// open over them. Wider screens show everything side by side and ignore all of this.
function markNav() {
  const over = !$("events").hidden ? "events" : !$("dash").hidden ? "account" : null;
  const active = over || document.body.dataset.mview || "home";
  $("mnav").querySelectorAll("[data-view]").forEach((b) => b.setAttribute("aria-current", String(b.dataset.view === active)));
}
function setView(view) {
  if (!PHONE()) return;
  if (view === "trip" && !document.body.classList.contains("has-trip")) view = "chat";
  if (view !== "events") closeEvents();
  if (view !== "account") closeDash();
  closePilgrimage();
  if (view === "events") openEvents();
  else if (view === "account") $("acctBtn").click();
  else {
    document.body.dataset.mview = view;
    window.scrollTo({ top: 0 });
    if (view === "chat") {
      $("mnav").querySelector('[data-view="chat"] .mnav-dot').hidden = true;
      requestAnimationFrame(() => { $("messages").scrollTop = $("messages").scrollHeight; });
    }
    if (view === "trip") $("mnav").querySelector('[data-view="trip"] .mnav-dot').hidden = true;
  }
  markNav();
}
$("mnav").addEventListener("click", (e) => {
  const b = e.target.closest("[data-view]");
  if (b) setView(b.dataset.view);
});
// A page opened or closed by its own buttons (Back, the account menu) keeps the bar in step.
new MutationObserver(markNav).observe(document.body, { subtree: true, attributes: true, attributeFilter: ["hidden"] });
/** A reply or a plan that arrives on another screen leaves a dot on its tab. */
function notify(view) {
  if (PHONE() && document.body.dataset.mview !== view) $("mnav").querySelector(`[data-view="${view}"] .mnav-dot`).hidden = false;
}

// ------------------------------------------------------------------ language
function greet() { addMessage("assistant", t("greeting")); }
function refreshLanguage() {
  applyStatic();
  renderChips();
  renderIdeaControls();
  renderHome();
  renderExamples();
  renderRoute();
  if (!$("wizard").hidden) { $("wMonth").innerHTML = $("ideaMonth").innerHTML; renderWizard(); }
  renderIdeas();
  if (state.trip && state.trip.plans && Object.keys(state.trip.plans).length) renderBoard();
  if (!state.tripId && $("messages").children.length <= 1) { $("messages").innerHTML = ""; greet(); }
  refreshAccountLanguage();
  refreshEventsLanguage();
  refreshPilgrimageLanguage();
  requestAnimationFrame(layoutGlobe);
}
$("langToggle").addEventListener("click", () => { setLang(getLang() === "ar" ? "en" : "ar"); refreshLanguage(); });

// ------------------------------------------------------------------ dark / light
const theme = () => document.documentElement.dataset.theme === "light" ? "light" : "dark";
function applyTheme(next) {
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem("theme", next); } catch (_) { /* storage unavailable */ }
  globe.setTheme(next);
  if (state.tab === "itinerary" && state.trip && state.trip.plans && Object.keys(state.trip.plans).length) renderTab();  // map tiles
}
$("themeToggle").addEventListener("click", () => applyTheme(theme() === "light" ? "dark" : "light"));
globe.setTheme(theme());

$("tabs").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-tab]");
  if (!b) return;
  state.tab = b.dataset.tab;
  renderTab();
});
$("composer").addEventListener("submit", (e) => {
  e.preventDefault();
  if (state.busy) return;  // keep the text: it can be sent when the answer arrives
  const v = $("input").value.trim();
  if (!v) return;
  setText($("input"), "");
  send(v);
});
wireTextBox($("input"), $("composer"), 140);
/** Forget the open trip (and any turn still running for it): the next message starts a new one. */
function resetTrip() {
  retireTurn();
  state.tripId = null; state.routeKey = ""; state.day = 1; state.tab = "itinerary";
  try { localStorage.removeItem("tripId"); } catch (_) { /* ignore */ }
  $("messages").innerHTML = "";
  globe.clearRoute();
  setTrip(null);
}
function newTrip() {
  closeDash();
  closeEvents();
  closePilgrimage();
  resetTrip();
  greet();
  setChatOpen(false);  // back to the two ways to start
  setView("home");
  $("hero").scrollTo({ top: 0 });
  setTimeout(() => $("qcInput").focus(), 50);
}
$("newTrip").addEventListener("click", newTrip);

/** Open a saved trip (from the dashboard): its conversation and its plan. */
async function openTrip(id) {
  const res = await fetch(`/api/trips/${encodeURIComponent(id)}`);
  if (!res.ok) return;
  const trip = await res.json();
  retireTurn();  // a turn still running for another trip must not land on this one
  state.tripId = trip.trip_id; state.routeKey = ""; state.day = 1; state.tab = "itinerary";
  try { localStorage.setItem("tripId", trip.trip_id); } catch (_) { /* ignore */ }
  $("messages").innerHTML = "";
  trip.conversation.forEach((m) => addMessage(m.role, m.content));
  pathButton(lastReply(), trip.metadata);  // the latest turn's route
  if (!trip.conversation.length) greet();
  setTrip(trip);
  setChatOpen(true);
  setView(Object.keys(trip.plans || {}).length ? "trip" : "chat");
}

/** Account preferences fill the form defaults (a saved "flying from" and currency). `force` after a settings change. */
function applyPrefs(prefs, force = false) {
  if (prefs.home_city && (force || !$("ideaFrom").value)) { $("ideaFrom").value = prefs.home_city; $("wFrom").value = prefs.home_city; }
  if (prefs.currency && (force || !+$("ideaBudget").value)) {
    for (const sel of [$("ideaCur"), $("wCur")]) {
      if (![...sel.options].some((o) => o.value === prefs.currency)) sel.add(new Option(prefs.currency, prefs.currency));
      sel.value = prefs.currency;
    }
  }
}

(async function boot() {
  applyStatic();
  renderHome();
  renderExamples();
  // Home has one entry point (the trip box): the chat opens once a conversation starts.
  let chatOpen = !!state.tripId;
  try { if (state.tripId) chatOpen = localStorage.getItem("chatOpen") !== "0"; } catch (_) { /* storage unavailable */ }
  setChatOpen(chatOpen);
  setView("home");  // phones: no stacked page while the trip loads
  try {
    const f = JSON.parse(localStorage.getItem("ideasForm") || "null");
    renderIdeaControls();
    if (f) {
      $("ideaBudget").value = f.budget || ""; $("ideaCur").value = f.currency || "USD"; $("ideaFrom").value = f.origin || "";
      $("ideaPax").value = f.travelers || 1; $("ideaLen").value = f.duration || "week";
      $("ideaMonth").value = f.month || ""; $("ideaMaxH").value = f.max_flight_hours || "";
      $("ideaDirect").checked = !!f.direct_only; $("ideaNotes").value = f.notes || "";
      ideasState.stops = Array.isArray(f.stops) ? f.stops.filter((x) => x && x.name).slice(0, 6) : [];
      $("ideaTo").value = ideasState.stops.length ? "" : (f.destination || "");
      renderRoute();
      ideasState.occasion = f.occasion || null;
      ideasState.interests = new Set(f.interests || []);
      if (f.start_date && f.start_date > isoDay(new Date())) { $("ideaStart").value = f.start_date; $("ideaEnd").value = f.end_date || ""; }
      setWhenMode(f.mode === "dates" && $("ideaStart").value ? "dates" : "flex");
      if (f.direct_only || f.max_flight_hours || f.notes) $("ideasMore").open = true;
      renderIdeaControls();
    }
  } catch (_) { renderIdeaControls(); /* storage unavailable */ }
  initAccount({
    openTrip, newTrip, openWizard, wikiImage, placeLabel, money, applyPrefs,
    tripDeleted: (id) => { if (state.tripId === id) newTrip(); },
  });
  $("acctBtn").addEventListener("click", closeEvents);  // the dashboard replaces the Events page
  // A trip around an event or a photographed landmark is a new trip: the open one stays saved in "My trips".
  const startTrip = (message) => {
    if (state.busy) return;
    resetTrip();
    greet();
    send(message);
  };
  initEvents({ beforeOpen: () => { closeDash(); closePilgrimage(); }, send: startTrip });
  initLandmarks({ modal, closeModal, md, send: startTrip });
  initPilgrimage({ beforeOpen: () => { closeDash(); closeEvents(); }, send: startTrip });
  $("acctBtn").addEventListener("click", closePilgrimage);
  if (state.tripId) {
    const res = await fetch(`/api/trips/${state.tripId}`);
    if (res.ok) {
      const t = await res.json();
      t.conversation.forEach((m) => addMessage(m.role, m.content));
      pathButton(lastReply(), t.metadata);
      setTrip(t);
      if (location.hash !== "#events" && location.hash !== "#hajj-umrah") {
        setView(Object.keys(t.plans || {}).length ? "trip" : chatOpen ? "chat" : "home");
      }
      return;
    }
    // Not ours any more (signed out, or deleted): start fresh.
    state.tripId = null;
    try { localStorage.removeItem("tripId"); } catch (_) { /* ignore */ }
  }
  greet();
  renderChips();
  layoutGlobe();
})();
