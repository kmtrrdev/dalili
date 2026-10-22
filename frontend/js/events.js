// The Events page: world-famous events in the coming months (championships, Grands Prix, festivals, carnivals,
// celebrations), each checked against Wikipedia, Wikidata and its official site - and one tap to plan a trip around it.
// Data: GET /api/events (built in the background on the server; complete=false while it is still being checked).
import { extend, getLang, locale, t } from "./i18n.js";
import { esc } from "./account.js";

extend({
  en: {
    evNav: "Events", evTitle: "Big events around the world",
    evSub: "Championships, Grands Prix, festivals and celebrations in the coming months - every one checked against Wikipedia and its official site. Pick one and Dalili plans the trip around it.",
    evAll: "All", evCat: { sports: "Sports", festival: "Festivals", music: "Music, film & arts", culture: "Culture & seasons" },
    evAnyCountry: "Every country", evPlan: "Plan a trip for this", evDetails: "Details",
    evConfirmed: "Confirmed dates", evUsual: "Usual dates · confirm", evFree: "Free or see the site",
    evFrom: (p) => `From ${p}`, evOfficial: "official site", evAi: "AI estimate",
    evLoading: "Checking the world's big events with Wikipedia and official sites…",
    evMore: "More events are still being checked - they appear here in a moment.",
    evEmpty: "No events here for now.", evHomeTitle: "Big events coming up",
    evHomeSub: "Plan a trip around a championship, a festival or a celebration.",
    evPlanMsg: (name, place, dates) => `Plan a trip to ${place} to attend ${name} (${dates})`,
    evOn: "On now",
  },
  ar: {
    evNav: "الإيفنتات", evTitle: "أكبر الإيفنتات حوالين العالم",
    evSub: "بطولات وسباقات ومهرجانات واحتفالات في الشهور الجاية - كل واحدة متأكدين منها من ويكيبيديا وموقعها الرسمي. اختار واحدة ودليلي يخطط الرحلة حواليها.",
    evAll: "الكل", evCat: { sports: "رياضة", festival: "مهرجانات", music: "موسيقى وسينما وفنون", culture: "ثقافة ومواسم" },
    evAnyCountry: "كل الدول", evPlan: "خطّطلي رحلة ليها", evDetails: "التفاصيل",
    evConfirmed: "مواعيد مؤكدة", evUsual: "مواعيدها المعتادة · اتأكد", evFree: "ببلاش أو شوف الموقع",
    evFrom: (p) => `من ${p}`, evOfficial: "الموقع الرسمي", evAi: "تقدير AI",
    evLoading: "بنراجع أكبر إيفنتات العالم مع ويكيبيديا والمواقع الرسمية…",
    evMore: "لسه في إيفنتات بتتراجع - هتظهر هنا كمان شوية.",
    evEmpty: "مفيش إيفنتات هنا دلوقتي.", evHomeTitle: "إيفنتات كبيرة جاية",
    evHomeSub: "خطّط رحلتك حوالين بطولة أو مهرجان أو احتفال.",
    evPlanMsg: (name, place, dates) => `عايز أسافر ${place} عشان أحضر ${name} (${dates})`,
    evOn: "شغّال دلوقتي",
  },
});

const $ = (id) => document.getElementById(id);
const ICON = { sports: "⚽", festival: "🎉", music: "🎬", culture: "🏮" };
const POLL_MS = 6000;
let app = null;          // hooks from app.js: send a chat message, close the other pages
let data = null;         // {complete, events}
let cat = "all";
let country = "";
let polls = 0;
let timer = null;

const ar = () => getLang() === "ar";
const nameOf = (e) => (ar() && e.name_ar ? e.name_ar : e.name);
function countryName(cc) {
  try { return new Intl.DisplayNames([locale()], { type: "region" }).of(cc) || cc; } catch (_) { return cc; }
}
const placeOf = (e) => [ar() && e.city_ar ? e.city_ar : e.city, countryName(e.country_code)].filter(Boolean).join(ar() ? "، " : ", ");
function day(iso, opts) { return new Date(`${iso}T12:00:00`).toLocaleDateString(locale(), opts); }
function span(e) {
  if (e.start === e.end) return day(e.start, { day: "numeric", month: "short", year: "numeric" });
  return `${day(e.start, { day: "numeric", month: "short" })} – ${day(e.end, { day: "numeric", month: "short", year: "numeric" })}`;
}
function money(m) {
  try { return new Intl.NumberFormat(locale(), { style: "currency", currency: m.currency, maximumFractionDigits: 0 }).format(m.amount); }
  catch (_) { return `${Math.round(m.amount)} ${m.currency}`; }
}
function ticket(e) {
  if (!e.ticket) return t("evFree");
  return `${t("evFrom", money(e.ticket))} · ${e.ticket.source === "official site" ? t("evOfficial") : t("evAi")}`;
}

function card(e) {
  const today = new Date().toISOString().slice(0, 10);
  const now = e.start <= today && e.end >= today;
  const img = e.image ? ` style="background-image:url('${esc(e.image)}')"` : "";
  return `<article class="ev-card">
    <div class="ev-img${e.image ? " has-img" : ""}"${img}><span class="ev-emoji" aria-hidden="true">${ICON[e.category] || "✨"}</span>
      <span class="ev-cat">${ICON[e.category] || ""} ${esc(t("evCat")[e.category] || e.category)}</span>
      ${now ? `<span class="ev-now">${t("evOn")}</span>` : ""}</div>
    <div class="ev-body">
      <b dir="auto">${esc(nameOf(e))}</b>
      <small>${esc(placeOf(e))}</small>
      <div class="ev-when">${esc(span(e))} <span class="badge ${e.dates_source === "usual dates" ? "warn" : "ok"}">${e.dates_source === "usual dates" ? t("evUsual") : t("evConfirmed")}</span></div>
      <p class="ev-why" dir="auto">${esc(ar() && e.why_ar ? e.why_ar : (e.why || e.description))}</p>
      <div class="ev-ticket">🎟 ${esc(ticket(e))}</div>
      <div class="ev-actions"><button class="btn primary small" type="button" data-plan="${esc(e.id)}">${t("evPlan")}</button>
        <a class="btn ghost small" href="${esc(e.website || e.wikipedia)}" target="_blank" rel="noopener">${t("evDetails")}</a></div>
    </div></article>`;
}

function visible() {
  return (data?.events || []).filter((e) => (cat === "all" || e.category === cat) && (!country || e.country_code === country));
}

function render() {
  if (!$("evBody") || $("events").hidden) return;
  const cats = ["all", ...Object.keys(ICON)];
  $("evTabs").innerHTML = cats.map((c) => `<button type="button" role="tab" data-cat="${c}" class="${c === cat ? "on" : ""}" aria-selected="${c === cat}">${c === "all" ? t("evAll") : `${ICON[c]} ${t("evCat")[c]}`}</button>`).join("");
  const codes = [...new Set((data?.events || []).map((e) => e.country_code))].sort((a, b) => countryName(a).localeCompare(countryName(b), locale()));
  $("evCountry").innerHTML = `<option value="">${t("evAnyCountry")}</option>` +
    codes.map((c) => `<option value="${c}"${c === country ? " selected" : ""}>${esc(countryName(c))}</option>`).join("");
  if (!data) { $("evBody").innerHTML = `<div class="d-loading"><span class="spinner"></span><p class="muted">${t("evLoading")}</p></div>`; return; }
  const list = visible();
  // Grouped by the month each event starts in.
  const groups = new Map();
  for (const e of list) {
    const k = e.start.slice(0, 7);
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k).push(e);
  }
  const more = data.complete ? "" : `<p class="ev-more"><span class="spinner small"></span>${t("evMore")}</p>`;
  $("evBody").innerHTML = more + (list.length ? [...groups].map(([k, es]) => `<section class="ev-month">
      <h3>${esc(day(`${k}-15`, { month: "long", year: "numeric" }))}</h3>
      <div class="ev-grid">${es.map(card).join("")}</div></section>`).join("")
    : (data.complete ? `<div class="d-empty"><span>🎟</span><b>${t("evEmpty")}</b></div>` : ""));
}

function renderHome() {
  const sec = $("evHome");
  const soon = (data?.events || []).slice().sort((a, b) => b.fame - a.fame).slice(0, 8)
    .sort((a, b) => a.start.localeCompare(b.start)).slice(0, 4);
  sec.hidden = !soon.length;
  $("evHomeList").innerHTML = soon.map(card).join("");
}

async function load() {
  clearTimeout(timer);
  try {
    const r = await fetch("/api/events");
    if (r.ok) data = await r.json();
  } catch (_) { /* offline: keep what we have */ }
  render();
  renderHome();
  if (data && !data.complete && polls++ < 40) timer = setTimeout(load, POLL_MS);
}

function plan(id) {
  const e = (data?.events || []).find((x) => x.id === id);
  if (!e) return;
  closeEvents();
  app.send(t("evPlanMsg", nameOf(e), placeOf(e), span(e)));
}

export function openEvents() {
  app.beforeOpen();
  $("events").hidden = false;
  document.body.classList.add("dash-open");
  $("events").scrollTo({ top: 0 });
  if (location.hash !== "#events") history.pushState(null, "", "#events");
  render();
  if (!data || !data.complete) load();
}
export function closeEvents() {
  if ($("events").hidden) return;
  $("events").hidden = true;
  document.body.classList.remove("dash-open");
  if (location.hash === "#events") history.replaceState(null, "", location.pathname + location.search);
}
export function refreshEventsLanguage() { render(); renderHome(); }

export function initEvents(hooks) {
  app = hooks;
  $("eventsBtn").addEventListener("click", openEvents);
  $("eventsBack").addEventListener("click", closeEvents);
  $("evHomeAll").addEventListener("click", openEvents);
  $("evTabs").addEventListener("click", (ev) => {
    const b = ev.target.closest("[data-cat]");
    if (b) { cat = b.dataset.cat; render(); }
  });
  $("evCountry").addEventListener("change", (ev) => { country = ev.target.value; render(); });
  for (const box of [$("evBody"), $("evHomeList")]) {
    box.addEventListener("click", (ev) => {
      const b = ev.target.closest("[data-plan]");
      if (b) plan(b.dataset.plan);
    });
  }
  document.addEventListener("keydown", (ev) => { if (ev.key === "Escape") closeEvents(); });
  window.addEventListener("popstate", () => { if (location.hash === "#events") openEvents(); else closeEvents(); });
  if (location.hash === "#events") openEvents(); else load();
}
