// Accounts, the dashboard and personal recommendations.
// Everything here talks to /api/auth, /api/me and /api/recommendations; the session lives in an HttpOnly cookie.
import { extend, getLang, locale, t } from "./i18n.js";

extend({
  en: {
    signIn: "Sign in", signUp: "Create account", signOut: "Sign out", close: "Close",
    authInT: "Welcome back", authInS: "Sign in to see your trips and suggestions.",
    authUpT: "Create your Dalili account", authUpS: "Free. Keep your trips and get suggestions that fit you.",
    aName: "Your name", aEmail: "Email", aPass: "Password", aShow: "Show password",
    aPassHint: "At least 8 characters, with letters and numbers.",
    aGoIn: "Sign in", aGoUp: "Create my account", aWorking: "One moment…",
    perk1: "Your trips saved on any device", perk2: "Suggestions picked for your taste", perk3: "Your own travel dashboard",
    asGuest: "Continue as a guest",
    eName: "Enter your name.", eEmail: "Enter a valid email address.", ePassLen: "Use at least 8 characters.",
    ePassMix: "Mix letters and numbers.", eWrong: "Email or password is incorrect.", eExists: "This email already has an account - sign in instead.",
    eMany: "Too many attempts. Please wait a few minutes and try again.", eNet: "Couldn't reach Dalili. Check your connection and try again.",
    eCurrent: "Your current password is incorrect.", eSame: "Choose a password different from the current one.",
    eMatch: "The two passwords don't match.",
    welcome: (n) => `Welcome, ${n}!`, welcomeBack: (n) => `Welcome back, ${n}!`, signedOut: "You're signed out.",
    guestNudge: "Create a free account to keep this trip on any device.", guestNudgeGo: "Create account",
    fyTitle: "Picked for you", fyAll: "See all", fySubUser: "Based on your trips, searches and interests.",
    fySubGuest: "Based on what you've explored so far - sign in to keep it.", fyReason: "Sign in to see all your suggestions.",
    dashBack: "Back to planning", dOverview: "Overview", dTrips: "My trips", dSettings: "Settings",
    hello: (n) => `Hi, ${n}`, memberSince: (d) => `Member since ${d}`, planNew: "Plan a new trip",
    nextTrip: "Your next trip", inDays: (n) => (n === 0 ? "today" : n === 1 ? "tomorrow" : `in ${n} days`), open: "Open",
    stTrips: "Trips planned", stCountries: "Countries", stDays: "Days of travel", stScore: "Average TripScore",
    tasteT: "Your travel taste", tasteS: "What Dalili has learned from your trips, searches and interests.",
    mapT: "Your taste map", mapS: "Every dot is a destination - similar places sit close together. The star is you.",
    you: "You", yours: "Places you planned or liked",
    coldT: "Tell us what you love", coldS: "Pick a few - your suggestions start right away and get better with every trip.",
    save: "Save", saved: "Saved", planThis: "Plan a trip", notForMe: "Not for me", undo: "Undo",
    dismissed: (c) => `${c} won't be suggested again.`, match: (p) => `${p}% match`,
    knownFor: "Known for", because: {
      planned: (c) => `Because you planned ${c}`, like: (c) => `Because you liked ${c}`, search: (c) => `Because you searched ${c}`,
      view: (c) => `Because you looked at ${c}`, interest: (i) => `Matches your love of ${i}`, similar: (c) => `Similar to ${c}`,
    },
    howT: "How your suggestions work",
    howP: (n, w) => `A Doc2Vec model we trained from scratch reads the travel guides of ${n} destinations (${w} words) and learns what each place feels like. Your taste is the mix of places you planned, searched and liked, and the interests you picked - recent ones count more.`,
    howSim: "Finds the same kind of place (Precision@5)", howInt: "Ranks places by interest (MAP)",
    ours: "Our model", tfidf: "TF-IDF baseline", random: "Random", lossT: "Training loss per epoch", howTest: "Measured on test destinations the model was never tuned on.",
    tAll: "All", tUpcoming: "Upcoming", tPast: "Past", tDrafts: "Drafts", noTrips: "No trips here yet.",
    noTripsP: "Plan your first trip - it will be saved here.", days: (n) => `${n} days`, travellers: (n) => `${n} traveller${n === 1 ? "" : "s"}`,
    stPlanned: "Planned", stDraft: "Draft", stNeeds: "Needs details", totalOf: (a, b) => `${a} of ${b}`, score: "TripScore",
    delTrip: "Delete trip", delQ: "Delete this trip?", del: "Delete", cancel: "Cancel", tripDeleted: "Trip deleted.",
    profT: "Profile", homeCity: "Usually flying from", homeCityPh: "e.g. Cairo", curPref: "Currency", intPref: "What you love",
    passT: "Password", curPass: "Current password", newPass: "New password", newPass2: "Repeat the new password", changePass: "Change password",
    passChanged: "Password changed. Other devices were signed out.",
    dangerT: "Delete account", dangerP: "This permanently deletes your account, your trips and your suggestions.",
    delAcc: "Delete my account", delAccQ: "Enter your password to confirm", accDeleted: "Your account was deleted.",
    emailLbl: "Email",
  },
  ar: {
    signIn: "تسجيل الدخول", signUp: "حساب جديد", signOut: "تسجيل الخروج", close: "إغلاق",
    authInT: "أهلاً بيك تاني", authInS: "سجّل دخولك عشان تشوف رحلاتك واقتراحاتك.",
    authUpT: "اعمل حسابك على دليلي", authUpS: "مجاناً. رحلاتك تفضل محفوظة واقتراحات على ذوقك.",
    aName: "اسمك", aEmail: "الإيميل", aPass: "كلمة السر", aShow: "إظهار كلمة السر",
    aPassHint: "٨ حروف على الأقل، فيها حروف وأرقام.",
    aGoIn: "دخول", aGoUp: "اعمل حسابي", aWorking: "لحظة…",
    perk1: "رحلاتك محفوظة على أي جهاز", perk2: "اقتراحات على ذوقك", perk3: "داشبورد خاصة بيك",
    asGuest: "كمّل كضيف",
    eName: "اكتب اسمك.", eEmail: "اكتب إيميل صحيح.", ePassLen: "استخدم ٨ حروف على الأقل.",
    ePassMix: "خلّيها فيها حروف وأرقام.", eWrong: "الإيميل أو كلمة السر مش صح.", eExists: "الإيميل ده عليه حساب بالفعل - سجّل دخول.",
    eMany: "محاولات كتير. استنى كام دقيقة وجرّب تاني.", eNet: "مش قادرين نوصل لدليلي. اتأكد من النت وجرّب تاني.",
    eCurrent: "كلمة السر الحالية مش صح.", eSame: "اختار كلمة سر مختلفة عن الحالية.",
    eMatch: "كلمتين السر مش زي بعض.",
    welcome: (n) => `أهلاً يا ${n}!`, welcomeBack: (n) => `أهلاً بيك تاني يا ${n}!`, signedOut: "سجّلت خروج.",
    guestNudge: "اعمل حساب مجاني عشان الرحلة دي تفضل معاك على أي جهاز.", guestNudgeGo: "اعمل حساب",
    fyTitle: "مختارة ليك", fyAll: "شوف الكل", fySubUser: "على حسب رحلاتك وبحثك واهتماماتك.",
    fySubGuest: "على حسب اللي استكشفته لحد دلوقتي - سجّل دخول عشان يتحفظ.", fyReason: "سجّل دخول عشان تشوف كل اقتراحاتك.",
    dashBack: "رجوع للتخطيط", dOverview: "نظرة عامة", dTrips: "رحلاتي", dSettings: "الإعدادات",
    hello: (n) => `أهلاً يا ${n}`, memberSince: (d) => `معانا من ${d}`, planNew: "خطّط رحلة جديدة",
    nextTrip: "رحلتك الجاية", inDays: (n) => (n === 0 ? "النهارده" : n === 1 ? "بكرة" : `بعد ${n} يوم`), open: "افتح",
    stTrips: "رحلات متخططة", stCountries: "دول", stDays: "أيام سفر", stScore: "متوسط TripScore",
    tasteT: "ذوقك في السفر", tasteS: "اللي دليلي اتعلمه من رحلاتك وبحثك واهتماماتك.",
    mapT: "خريطة ذوقك", mapS: "كل نقطة وجهة - الأماكن الشبه بعض قريبة من بعض. النجمة دي انت.",
    you: "انت", yours: "أماكن خططتلها أو عجبتك",
    coldT: "قولنا بتحب إيه", coldS: "اختار كام حاجة - الاقتراحات هتبدأ على طول وتتحسن مع كل رحلة.",
    save: "حفظ", saved: "اتحفظ", planThis: "خطّط رحلة", notForMe: "مش لي", undo: "تراجع",
    dismissed: (c) => `مش هنقترح ${c} تاني.`, match: (p) => `تطابق ${p}%`,
    knownFor: "مشهورة بـ", because: {
      planned: (c) => `عشان خططت لـ ${c}`, like: (c) => `عشان عجبتك ${c}`, search: (c) => `عشان دوّرت على ${c}`,
      view: (c) => `عشان بصّيت على ${c}`, interest: (i) => `تناسب حبك لـ${i}`, similar: (c) => `شبه ${c}`,
    },
    howT: "الاقتراحات بتشتغل إزاي",
    howP: (n, w) => `موديل Doc2Vec دربناه من الصفر بيقرا أدلة السفر بتاعة ${n} وجهة (${w} كلمة) ويتعلم إحساس كل مكان. ذوقك هو خليط الأماكن اللي خططتلها ودوّرت عليها وعجبتك والاهتمامات اللي اخترتها - والأحدث ليه وزن أكبر.`,
    howSim: "بيلاقي أماكن من نفس النوع (Precision@5)", howInt: "بيرتب الأماكن حسب الاهتمام (MAP)",
    ours: "الموديل بتاعنا", tfidf: "TF-IDF (مرجع)", random: "عشوائي", lossT: "الـ loss في كل epoch", howTest: "متقاس على وجهات اختبار الموديل ماتظبطش عليها.",
    tAll: "الكل", tUpcoming: "الجاية", tPast: "اللي فاتت", tDrafts: "مسودات", noTrips: "مفيش رحلات هنا لسه.",
    noTripsP: "خطّط أول رحلة - هتتحفظ هنا.", days: (n) => `${n} يوم`, travellers: (n) => `${n} ${n === 1 ? "مسافر" : "مسافرين"}`,
    stPlanned: "متخططة", stDraft: "مسودة", stNeeds: "ناقصها تفاصيل", totalOf: (a, b) => `${a} من ${b}`, score: "TripScore",
    delTrip: "مسح الرحلة", delQ: "تمسح الرحلة دي؟", del: "امسح", cancel: "إلغاء", tripDeleted: "الرحلة اتمسحت.",
    profT: "البروفايل", homeCity: "بتسافر عادةً من", homeCityPh: "مثلاً القاهرة", curPref: "العملة", intPref: "بتحب إيه",
    passT: "كلمة السر", curPass: "كلمة السر الحالية", newPass: "كلمة السر الجديدة", newPass2: "كرر كلمة السر الجديدة", changePass: "غيّر كلمة السر",
    passChanged: "كلمة السر اتغيرت. الأجهزة التانية اتعملها تسجيل خروج.",
    dangerT: "مسح الحساب", dangerP: "ده هيمسح حسابك ورحلاتك واقتراحاتك نهائياً.",
    delAcc: "امسح حسابي", delAccQ: "اكتب كلمة السر للتأكيد", accDeleted: "حسابك اتمسح.",
    emailLbl: "الإيميل",
  },
});

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const INTERESTS = [["beach", "🏖️"], ["culture", "🏛️"], ["history", "🏺"], ["nature", "🌿"], ["ski", "⛷️"],
  ["food", "🍽️"], ["nightlife", "🌙"], ["shopping", "🛍️"], ["relax", "🧖"], ["adventure", "🧗"]];
const EMOJI = Object.fromEntries(INTERESTS);
export const CURRENCIES = ["USD", "EUR", "EGP", "SAR", "AED", "KWD", "QAR", "GBP"];

export const account = { user: null };
let app = null;            // hooks from app.js (openTrip, newTrip, openWizard, wikiImage, placeLabel, money, applyPrefs)
let authMode = "signin";
let afterAuth = null;      // what to do once signed in (e.g. open the dashboard)
let dashTab = "overview";
let tripFilter = "all";
let dashData = null;

// ------------------------------------------------------------------ API
async function api(path, { method = "GET", body } = {}) {
  let res;
  try {
    res = await fetch(path, { method, credentials: "same-origin", headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined });
  } catch (_) {
    const e = new Error(t("eNet")); e.status = 0; throw e;
  }
  let data = null;
  try { data = await res.json(); } catch (_) { /* empty body */ }
  if (!res.ok) {
    const e = new Error((data && data.detail) || res.statusText);
    e.status = res.status; e.field = data && data.field; throw e;
  }
  return data;
}

/** A server message in the page language (the API answers in English). */
function localError(err) {
  const m = err.message || "";
  if (err.status === 0) return t("eNet");
  if (err.status === 429) return t("eMany");
  if (err.status === 409) return t("eExists");
  const map = [[/valid email/i, "eEmail"], [/your name/i, "eName"], [/at least 8/i, "ePassLen"], [/letters and numbers/i, "ePassMix"],
    [/email or password/i, "eWrong"], [/current password/i, "eCurrent"], [/different from/i, "eSame"], [/password is incorrect/i, "eWrong"]];
  const hit = map.find(([re]) => re.test(m));
  return hit ? t(hit[1]) : m;
}

export function logActivity(kind, city) {
  if (!city) return;
  fetch("/api/activity", { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ kind, city: String(city).slice(0, 80) }) }).catch(() => { /* best effort */ });
}

// ------------------------------------------------------------------ toast
let toastTimer = null;
export function toast(msg, action = null) {
  const el = $("toast");
  el.innerHTML = `<span>${esc(msg)}</span>` + (action ? `<button type="button" class="toast-act">${esc(action.label)}</button>` : "");
  el.hidden = false;
  el.classList.remove("show"); void el.offsetWidth; el.classList.add("show");
  if (action) el.querySelector(".toast-act").onclick = () => { el.hidden = true; action.run(); };
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, action ? 7000 : 3500);
}

// ------------------------------------------------------------------ header button
const initial = (name) => (name || "?").trim().charAt(0).toUpperCase();
const firstName = (name) => (name || "").trim().split(/\s+/)[0];

function renderAcctBtn() {
  const b = $("acctBtn");
  if (account.user) {
    b.classList.add("signed");
    b.innerHTML = `<span class="av">${esc(initial(account.user.name))}</span><span class="an">${esc(firstName(account.user.name))}</span>`;
    b.title = account.user.email;
  } else {
    b.classList.remove("signed");
    b.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21a8 8 0 0 1 16 0" /></svg><span>${t("signIn")}</span>`;
    b.title = t("signIn");
  }
  b.setAttribute("aria-label", b.title);
}

// ------------------------------------------------------------------ sign in / sign up
// The sign-in dialog is created the first time it's opened, never shipped in the page HTML: a password field on a
// new site's home page is what automated phishing scanners flag.
const AUTH_HTML = `
  <div class="modal-wrap auth-wrap" id="authWrap" hidden>
    <div class="modal auth" role="dialog" aria-modal="true" aria-labelledby="authTitle">
      <button class="icon-btn modal-x" type="button" id="authClose" data-i18n-title="close">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg></button>
      <div class="auth-head">
        <span class="brand-mark" aria-hidden="true"><svg viewBox="0 0 24 24"><path class="plane" d="M21 16v-2l-8-5V3.5a1.5 1.5 0 0 0-3 0V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5z" /></svg></span>
        <h2 id="authTitle"></h2>
        <p id="authSub"></p>
      </div>
      <div class="seg auth-tabs" id="authTabs" role="tablist">
        <button type="button" data-mode="signin" role="tab" data-i18n="signIn"></button>
        <button type="button" data-mode="signup" role="tab" data-i18n="signUp"></button>
      </div>
      <form class="auth-form" id="authForm" novalidate>
        <label class="af" id="afName"><span data-i18n="aName"></span>
          <input id="aName" class="w-in" autocomplete="name" maxlength="60"><small class="af-err" data-for="name"></small></label>
        <label class="af"><span data-i18n="aEmail"></span>
          <input id="aEmail" class="w-in" type="email" autocomplete="email" inputmode="email" maxlength="254" dir="ltr">
          <small class="af-err" data-for="email"></small></label>
        <label class="af"><span data-i18n="aPass"></span>
          <span class="pw"><input id="aPass" class="w-in" type="password" autocomplete="current-password" maxlength="128" dir="ltr">
            <button type="button" class="pw-eye" id="aEye" data-i18n-title="aShow">
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12zM12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6z" /></svg></button></span>
          <span class="pw-meter" id="pwMeter" aria-hidden="true"><i></i></span>
          <small class="af-hint" id="pwHint" data-i18n="aPassHint"></small>
          <small class="af-err" data-for="password"></small></label>
        <p class="auth-err" id="authErr" role="alert" hidden></p>
        <button class="btn primary auth-go" type="submit" id="authGo"></button>
      </form>
      <ul class="auth-perks">
        <li data-i18n="perk1"></li><li data-i18n="perk2"></li><li data-i18n="perk3"></li>
      </ul>
      <button class="auth-guest" type="button" id="authGuest" data-i18n="asGuest"></button>
    </div>
  </div>`;

function ensureAuthDom() {
  if ($("authWrap")) return;
  document.body.insertAdjacentHTML("beforeend", AUTH_HTML);
  const wrap = $("authWrap");
  wrap.querySelectorAll("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n); });
  wrap.querySelectorAll("[data-i18n-title]").forEach((el) => {
    el.title = t(el.dataset.i18nTitle); el.setAttribute("aria-label", el.title);
  });
  $("authClose").addEventListener("click", closeAuth);
  $("authGuest").addEventListener("click", closeAuth);
  wrap.addEventListener("click", (e) => { if (e.target.id === "authWrap") closeAuth(); });
  $("authTabs").addEventListener("click", (e) => {
    const b = e.target.closest("[data-mode]");
    if (!b) return;
    authMode = b.dataset.mode; renderAuth();
    (authMode === "signup" ? $("aName") : $("aEmail")).focus();
  });
  $("authForm").addEventListener("submit", submitAuth);
  $("authForm").addEventListener("input", (e) => {  // an error goes away as soon as the field is edited
    const field = { aName: "name", aEmail: "email", aPass: "password" }[e.target.id];
    if (field) fieldError(field, "");
    $("authErr").hidden = true;
  });
  $("aEye").addEventListener("click", () => {
    const p = $("aPass"); p.type = p.type === "password" ? "text" : "password"; p.focus();
  });
  $("aPass").addEventListener("input", () => {
    $("pwMeter").dataset.s = $("aPass").value ? strength($("aPass").value) : "";
  });
}

export function openAuth(mode = "signin", subtitle = null, then = null) {
  ensureAuthDom();
  authMode = mode;
  afterAuth = then;
  $("authWrap").hidden = false;
  $("authForm").reset();
  $("authForm").querySelectorAll(".af-err").forEach((e) => { e.textContent = ""; });
  $("authForm").querySelectorAll(".w-in").forEach((e) => e.classList.remove("bad"));
  $("authErr").hidden = true;
  renderAuth(subtitle);
  document.addEventListener("keydown", authKeys);
  setTimeout(() => (mode === "signup" ? $("aName") : $("aEmail")).focus(), 60);
}
function closeAuth() {
  if ($("authWrap")) $("authWrap").hidden = true;
  document.removeEventListener("keydown", authKeys);
}
function authKeys(e) { if (e.key === "Escape") closeAuth(); }

function renderAuth(subtitle = null) {
  const up = authMode === "signup";
  $("authTitle").textContent = t(up ? "authUpT" : "authInT");
  $("authSub").textContent = subtitle || t(up ? "authUpS" : "authInS");
  $("authTabs").querySelectorAll("button").forEach((b) => {
    const on = b.dataset.mode === authMode;
    b.classList.toggle("on", on); b.setAttribute("aria-selected", on);
  });
  $("afName").hidden = !up;
  $("pwHint").hidden = !up;
  $("pwMeter").hidden = !up;
  $("aPass").autocomplete = up ? "new-password" : "current-password";
  $("authGo").textContent = t(up ? "aGoUp" : "aGoIn");
  document.querySelector(".auth-perks").hidden = !up;
}

function passwordProblem(p) {
  if ((p || "").length < 8) return t("ePassLen");
  if (!/[A-Za-z؀-ۿ]/.test(p) || !/\d/.test(p)) return t("ePassMix");
  return null;
}
function strength(p) {
  let s = 0;
  if (p.length >= 8) s++;
  if (p.length >= 12) s++;
  if (/[a-z]/.test(p) && /[A-Z]/.test(p)) s++;
  if (/\d/.test(p)) s++;
  if (/[^A-Za-z0-9]/.test(p)) s++;
  return Math.min(4, s);
}

function fieldError(field, msg) {
  const el = $("authForm").querySelector(`.af-err[data-for="${field}"]`);
  const input = { name: "aName", email: "aEmail", password: "aPass" }[field];
  if (el) el.textContent = msg || "";
  if (input) $(input).classList.toggle("bad", !!msg);
}

async function submitAuth(e) {
  e.preventDefault();
  const up = authMode === "signup";
  const name = $("aName").value.trim(), email = $("aEmail").value.trim(), password = $("aPass").value;
  ["name", "email", "password"].forEach((f) => fieldError(f, ""));
  $("authErr").hidden = true;
  let bad = false;
  if (up && !name) { fieldError("name", t("eName")); bad = true; }
  if (!/^[^@\s]+@[^@\s]+\.[a-z]{2,}$/i.test(email)) { fieldError("email", t("eEmail")); bad = true; }
  const pp = up ? passwordProblem(password) : (password ? null : t("ePassLen"));
  if (pp) { fieldError("password", pp); bad = true; }
  if (bad) { $("authForm").querySelector(".w-in.bad")?.focus(); return; }

  const go = $("authGo");
  go.disabled = true; go.textContent = t("aWorking");
  try {
    const r = await api(up ? "/api/auth/signup" : "/api/auth/signin", { method: "POST", body: up ? { name, email, password } : { email, password } });
    account.user = r.user;
    closeAuth();
    renderAcctBtn();
    toast(t(up ? "welcome" : "welcomeBack", firstName(r.user.name)));
    app.applyPrefs?.(r.user.prefs || {});
    loadForYou();
    const next = afterAuth; afterAuth = null;
    if (next) next();
  } catch (err) {
    const msg = localError(err);
    if (err.field && err.status !== 401) fieldError(err.field, msg);
    else { $("authErr").textContent = msg; $("authErr").hidden = false; }
  } finally {
    go.disabled = false; go.textContent = t(up ? "aGoUp" : "aGoIn");
  }
}

async function signOut() {
  try { await api("/api/auth/signout", { method: "POST" }); } catch (_) { /* the cookie is cleared either way */ }
  account.user = null;
  renderAcctBtn();
  closeDash();
  app.newTrip();   // the current trip belonged to the account
  toast(t("signedOut"));
  loadForYou();
}

// ------------------------------------------------------------------ recommendations
const REASONS = new Set(["planned", "like", "search", "view", "interest", "similar"]);
const reasonText = (r) => {
  if (!r || !REASONS.has(r.type)) return "";
  return t(`because.${r.type}`, r.type === "interest" ? t(`int.${r.interest}`) : app.placeLabel(r.city));
};
const TAG_TINT = { beach: "#2bb3d6", culture: "#9b8cff", history: "#d99a3e", nature: "#44c267", ski: "#8ec9ff",
  food: "#ff8a5c", nightlife: "#d25bd8", shopping: "#ff6b8b", relax: "#3de0d0", adventure: "#f2c14e" };

function recCard(r) {
  const tags = r.tags.slice(0, 2).map((g) => `<span class="rec-tag">${EMOJI[g] || ""} ${esc(t(`int.${g}`))}</span>`).join("");
  return `<article class="rec" data-city="${esc(r.name)}" style="--tint:${TAG_TINT[r.tags[0]] || "#3de0d0"}">
    <div class="rec-img${r.image ? " has-img" : ""}" ${r.image ? `style="background-image:url('${esc(r.image).replace(/'/g, "%27")}')"` : `data-wiki="${esc(r.name)}"`}>
      <span class="rec-emoji" aria-hidden="true">${EMOJI[r.tags[0]] || "✈️"}</span>
      <span class="rec-match">${esc(t("match", r.match))}</span>
      <button type="button" class="rec-x" data-act="dismiss" title="${esc(t("notForMe"))}" aria-label="${esc(t("notForMe"))}">×</button></div>
    <div class="rec-body">
      <b>${esc(app.placeLabel(r.name))}</b><small>${esc(r.country)}</small>
      <p class="rec-why">✨ ${esc(reasonText(r.reason))}</p>
      <div class="rec-tags">${tags}</div>
      <p class="rec-kw"><span>${esc(t("knownFor"))}:</span> <bdi dir="ltr">${r.keywords.map(esc).join(" · ")}</bdi></p>
      <button type="button" class="btn small primary" data-act="plan">${esc(t("planThis"))}</button>
    </div></article>`;
}

function paintImages(root) {
  root.querySelectorAll("[data-wiki]").forEach(async (el) => {
    const src = await app.wikiImage(el.dataset.wiki.replace(/ /g, "_"));
    if (src) { el.style.backgroundImage = `url('${src.replace(/'/g, "%27")}')`; el.classList.add("has-img"); }
  });
}

function bindRecs(root, reload) {
  root.onclick = async (e) => {
    const b = e.target.closest("[data-act]");
    const card = e.target.closest(".rec");
    if (!b || !card) return;
    const city = card.dataset.city;
    if (b.dataset.act === "plan") {
      logActivity("like", city);
      closeDash();
      app.openWizard({ where: "place", stops: [city], step: 1 });
    } else if (b.dataset.act === "dismiss") {
      card.classList.add("gone");
      logActivity("dismiss", city);
      toast(t("dismissed", app.placeLabel(city)), { label: t("undo"), run: async () => {
        await fetch(`/api/activity/dismiss?city=${encodeURIComponent(city)}`, { method: "DELETE", credentials: "same-origin" });
        reload();
      } });
      setTimeout(reload, 350);
    }
  };
}

/** Home page strip: shown as soon as the model has something to go on (for guests too). */
export async function loadForYou() {
  const sec = $("forYou");
  try {
    const r = await api("/api/recommendations?limit=5");
    if (r.cold_start || !r.items.length) { sec.hidden = true; return; }
    $("forYouSub").textContent = t(account.user ? "fySubUser" : "fySubGuest");
    $("forYouRecs").innerHTML = r.items.map(recCard).join("");
    sec.hidden = false;
    paintImages($("forYouRecs"));
    bindRecs($("forYouRecs"), loadForYou);
  } catch (_) { sec.hidden = true; }
}

// ------------------------------------------------------------------ dashboard
export async function openDash(tab = "overview") {
  if (!account.user) { openAuth("signin", t("fyReason"), () => openDash(tab)); return; }
  dashTab = tab;
  $("dash").hidden = false;
  document.body.classList.add("dash-open");
  document.addEventListener("keydown", dashKeys);
  $("dash").scrollTo({ top: 0 });
  renderDashTabs();
  $("dashBody").innerHTML = `<div class="d-loading"><span class="spinner"></span></div>`;
  await refreshDash();
}
export function closeDash() {
  if ($("dash").hidden) return;
  $("dash").hidden = true;
  document.body.classList.remove("dash-open");
  document.removeEventListener("keydown", dashKeys);
}
function dashKeys(e) { if (e.key === "Escape" && (!$("authWrap") || $("authWrap").hidden)) closeDash(); }

function renderDashTabs() {
  $("dashTabs").querySelectorAll("button").forEach((b) => {
    const on = b.dataset.tab === dashTab;
    b.classList.toggle("on", on); b.setAttribute("aria-selected", on);
  });
}

async function refreshDash() {
  try {
    const [d, recs, map] = await Promise.all([
      api("/api/me/dashboard"),
      api("/api/recommendations?limit=8").catch(() => null),
      api("/api/recommendations/map").catch(() => null),
    ]);
    dashData = { ...d, recs, map };
    account.user = d.user;
    renderAcctBtn();
  } catch (err) {
    if (err.status === 401) { account.user = null; renderAcctBtn(); closeDash(); openAuth("signin"); return; }
    $("dashBody").innerHTML = `<p class="d-empty">${esc(localError(err))}</p>`;
    return;
  }
  renderDash();
}

function renderDash() {
  if (!dashData) return;
  renderDashTabs();
  const body = $("dashBody");
  body.innerHTML = dashTab === "trips" ? tripsView() : dashTab === "settings" ? settingsView() : overviewView();
  paintImages(body);
  if (dashTab === "overview") {
    const recs = body.querySelector(".recs");
    if (recs) bindRecs(recs, refreshDash);
    loadModelReport();
  }
}

/** "Rome → Florence" (reads right to left in Arabic, so the arrow turns around). */
const route = (cities) => cities.map((c) => `<bdi>${esc(app.placeLabel(c))}</bdi>`).join(getLang() === "ar" ? " ← " : " → ");
const fmtDay = (iso, o = { day: "numeric", month: "short" }) => new Date(iso + "T12:00:00").toLocaleDateString(locale(), o);
const daysUntil = (iso) => Math.round((new Date(iso + "T00:00:00") - new Date(new Date().toDateString())) / 86400000);

function overviewView() {
  const { user, stats, next_trip: nt, recs, map } = dashData;
  const since = new Date(user.created_at).toLocaleDateString(locale(), { month: "long", year: "numeric" });
  const stat = (v, k, ic) => `<div class="d-stat"><span class="ds-ic" aria-hidden="true">${ic}</span><b>${v ?? "–"}</b><small>${esc(t(k))}</small></div>`;
  let html = `<div class="d-hello"><span class="av big">${esc(initial(user.name))}</span>
      <div><h1 id="dashTitle">${esc(t("hello", firstName(user.name)))} 👋</h1><p>${esc(t("memberSince", since))}</p></div>
      <button type="button" class="btn primary" data-dash="new">＋ ${esc(t("planNew"))}</button></div>`;
  if (nt) {
    const n = daysUntil(nt.start_date);
    html += `<button type="button" class="d-next" data-open="${esc(nt.trip_id)}">
      <span class="dn-img" data-wiki="${esc(nt.cities[0] || "")}"></span>
      <span class="dn-body"><small>${esc(t("nextTrip"))} · ${esc(t("inDays", n))}</small>
        <b>${route(nt.cities)}</b>
        <span>${esc(fmtDay(nt.start_date))} – ${esc(fmtDay(nt.end_date, { day: "numeric", month: "short", year: "numeric" }))}</span></span>
      <span class="btn small">${esc(t("open"))}</span></button>`;
  }
  html += `<div class="d-stats">${stat(stats.planned, "stTrips", "🧳")}${stat(stats.countries, "stCountries", "🌍")}
    ${stat(stats.days, "stDays", "📅")}${stat(stats.avg_score, "stScore", "⭐")}</div>`;

  // Picked for you (or the first-time picker)
  html += `<section class="d-sec"><div class="sec-head"><h2>${esc(t("fyTitle"))}</h2>`;
  if (!recs || recs.cold_start || !recs.items.length) {
    const mine = new Set((user.prefs || {}).interests || []);
    html += `<p>${esc(t("coldS"))}</p></div><div class="d-cold"><h3>${esc(t("coldT"))}</h3>
      <div class="chipset" id="coldInts">${INTERESTS.map(([k, e]) => `<button type="button" class="pchip${mine.has(k) ? " on" : ""}" data-int="${k}"><span>${e}</span>${esc(t(`int.${k}`))}</button>`).join("")}</div>
      <button type="button" class="btn primary" data-dash="save-ints">${esc(t("save"))}</button></div></section>`;
  } else {
    html += `<p>${esc(t("fySubUser"))}</p></div><div class="recs">${recs.items.map(recCard).join("")}</div></section>`;
  }

  // Taste profile + map
  if (recs && recs.taste && recs.taste.length) {
    const bars = recs.taste.map((x) => `<div class="tb"><span>${EMOJI[x.interest]} ${esc(t(`int.${x.interest}`))}</span>
      <i><em style="width:${x.score}%;background:${TAG_TINT[x.interest]}"></em></i><b>${x.score}</b></div>`).join("");
    html += `<section class="d-sec"><div class="sec-head"><h2>${esc(t("tasteT"))}</h2><p>${esc(t("tasteS"))}</p></div>
      <div class="taste-grid"><div class="taste-bars">${bars}</div>
      <figure class="taste-map">${tasteMap(map)}<figcaption><b>${esc(t("mapT"))}</b> · ${esc(t("mapS"))}</figcaption></figure></div></section>`;
  }
  html += `<details class="d-model" id="dModel"><summary>🧠 ${esc(t("howT"))}</summary><div class="dm-body" id="dmBody"></div></details>`;
  return html;
}

function tasteMap(map) {
  if (!map || !map.points || !map.points.length) return "";
  const xs = map.points.map((p) => p.x), ys = map.points.map((p) => p.y);
  if (map.me) { xs.push(map.me[0]); ys.push(map.me[1]); }
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const W = 100, H = 62, pad = 4;
  const px = (x) => pad + ((x - x0) / (x1 - x0 || 1)) * (W - 2 * pad);
  const py = (y) => pad + ((y - y0) / (y1 - y0 || 1)) * (H - 2 * pad);
  // the user's places last, so they're drawn on top
  const pts = [...map.points].sort((a, b) => a.mine - b.mine);
  const dots = pts.map((p) => `<circle cx="${px(p.x).toFixed(2)}" cy="${py(p.y).toFixed(2)}" r="${p.mine ? 1.35 : 0.75}"
      fill="${TAG_TINT[p.tag] || "#888"}" class="${p.mine ? "mine" : ""}"><title>${esc(p.name)}, ${esc(p.country)}</title></circle>`).join("");
  // Label the user's places, skipping any label that would sit on top of one already placed.
  const placed = [];
  if (map.me) placed.push([px(map.me[0]), py(map.me[1]) - 4.2]);
  const labels = pts.filter((p) => p.mine).map((p) => {
    const x = px(p.x), y = py(p.y) - 2.2;
    if (placed.some(([a, b]) => Math.abs(a - x) < 9 && Math.abs(b - y) < 2.8)) return "";
    placed.push([x, y]);
    return `<text x="${x.toFixed(2)}" y="${y.toFixed(2)}" class="tm-lbl">${esc(app.placeLabel(p.name))}</text>`;
  }).join("");
  const me = map.me ? `<g class="tm-me" transform="translate(${px(map.me[0]).toFixed(2)} ${py(map.me[1]).toFixed(2)})">
      <circle r="3.4" class="halo"/><path d="M0-2.4l.7 1.5 1.6.2-1.2 1.1.3 1.6L0 1.2l-1.4.8.3-1.6-1.2-1.1 1.6-.2z"/>
      <text y="-4.2">${esc(t("you"))}</text></g>` : "";
  const legend = Object.entries(TAG_TINT).map(([k, c]) => `<span><i style="background:${c}"></i>${esc(t(`int.${k}`))}</span>`).join("");
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(t("mapT"))}">${dots}${labels}${me}</svg><div class="tm-legend">${legend}</div>`;
}

async function loadModelReport() {
  const box = $("dmBody");
  if (!box) return;
  try {
    const r = await api("/api/recommendations/model");
    const n = new Intl.NumberFormat(locale());
    const sim = r.test["similar_places_p@5"];
    const ints = r.test.interests;
    const bar = (v, cls) => `<i class="mb ${cls}"><em style="width:${Math.round(v * 100)}%"></em></i><b>${v.toFixed(2)}</b>`;
    const row = (label, ours, base, rnd) => `<div class="mrow"><span class="ml">${esc(label)}</span>
      <span class="mv"><small>${esc(t("ours"))}</small>${bar(ours, "ours")}</span>
      <span class="mv"><small>${esc(t("tfidf"))}</small>${bar(base, "base")}</span>
      <span class="mv"><small>${esc(t("random"))}</small>${bar(rnd, "rnd")}</span></div>`;
    const loss = r.loss_per_epoch || [];
    const lo = Math.min(...loss), hi = Math.max(...loss);
    const pts = loss.map((v, i) => `${(i / Math.max(loss.length - 1, 1) * 100).toFixed(1)},${(4 + (hi - v) / (hi - lo || 1) * 22).toFixed(1)}`).join(" ");
    box.innerHTML = `<p>${esc(t("howP", r.data.destinations, n.format(r.data.tokens)))}</p>
      ${row(t("howSim"), sim.doc2vec, sim.tfidf, sim.random)}
      ${row(t("howInt"), ints.doc2vec.map, ints.tfidf.map, ints.random.map)}
      <div class="mloss"><small>${esc(t("lossT"))} (${loss.length})</small>
        <svg viewBox="0 0 100 30" preserveAspectRatio="none"><polyline points="${pts}" /></svg>
        <small dir="ltr">${loss[0]?.toFixed(2)} → ${loss[loss.length - 1]?.toFixed(2)}</small></div>
      <p class="muted small">${esc(t("howTest"))} · dim ${r.config.dim} · ${r.config.epochs} epochs · ${n.format(r.data.vocabulary)} words</p>`;
  } catch (_) { box.closest("details").hidden = true; }
}

function tripsView() {
  const today = new Date().toISOString().slice(0, 10);
  const all = dashData.trips;
  const groups = {
    all: all, upcoming: all.filter((x) => x.status === "planned" && (x.start_date || "") >= today),
    past: all.filter((x) => x.status === "planned" && (x.end_date || "9") < today), drafts: all.filter((x) => x.status !== "planned"),
  };
  const list = groups[tripFilter] || all;
  const seg = ["all", "upcoming", "past", "drafts"].map((k) => `<button type="button" data-filter="${k}" class="${k === tripFilter ? "on" : ""}">
      ${esc(t(`t${k[0].toUpperCase()}${k.slice(1)}`))} <em>${groups[k].length}</em></button>`).join("");
  const rows = list.map((x) => {
    const st = x.status === "planned" ? ["ok", "stPlanned"] : x.status === "needs_input" ? ["warn", "stNeeds"] : ["info", "stDraft"];
    const when = x.start_date ? `${fmtDay(x.start_date)} – ${fmtDay(x.end_date, { day: "numeric", month: "short", year: "numeric" })}` : "";
    const meta = [when, x.days ? t("days", x.days) : "", x.travelers ? t("travellers", x.travelers) : ""].filter(Boolean).join(" · ");
    const total = x.total && x.currency ? t("totalOf", app.money(x.total, x.currency), app.money(x.budget || 0, x.currency)) : "";
    return `<article class="trip-row" data-id="${esc(x.trip_id)}">
      <span class="tr-img" data-wiki="${esc(x.cities[0] || "")}"></span>
      <div class="tr-main"><b>${x.cities.length ? route(x.cities) : "…"}</b>
        <small>${esc(meta)}</small>
        <div class="tr-meta"><span class="badge ${st[0]}">${esc(t(st[1]))}</span>${total ? `<span>${esc(total)}</span>` : ""}
          ${x.score != null ? `<span>${esc(t("score"))} <b>${x.score}</b></span>` : ""}</div></div>
      <div class="tr-act"><button type="button" class="btn small" data-trip="open">${esc(t("open"))}</button>
        <button type="button" class="icon-btn" data-trip="ask" title="${esc(t("delTrip"))}" aria-label="${esc(t("delTrip"))}">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3" /></svg></button></div>
      <div class="tr-confirm" hidden><span>${esc(t("delQ"))}</span><button type="button" class="btn small danger" data-trip="del">${esc(t("del"))}</button>
        <button type="button" class="btn small ghost" data-trip="keep">${esc(t("cancel"))}</button></div></article>`;
  }).join("");
  const empty = `<div class="d-empty"><span>🧳</span><b>${esc(t("noTrips"))}</b><p>${esc(t("noTripsP"))}</p>
      <button type="button" class="btn primary" data-dash="new">＋ ${esc(t("planNew"))}</button></div>`;
  return `<h1 class="sr-only" id="dashTitle">${esc(t("dTrips"))}</h1><div class="seg trip-filter" id="tripFilter">${seg}</div>
    <div class="trip-list">${rows || empty}</div>`;
}

function settingsView() {
  const u = dashData.user, p = u.prefs || {};
  const mine = new Set(p.interests || []);
  return `<h1 class="sr-only" id="dashTitle">${esc(t("dSettings"))}</h1>
  <form class="d-card" id="profForm" novalidate><h2>${esc(t("profT"))}</h2>
    <div class="d-grid">
      <label class="af"><span>${esc(t("aName"))}</span><input class="w-in" name="name" maxlength="60" value="${esc(u.name)}" autocomplete="name"></label>
      <label class="af"><span>${esc(t("emailLbl"))}</span><input class="w-in" value="${esc(u.email)}" disabled dir="ltr"></label>
      <label class="af"><span>${esc(t("homeCity"))}</span><input class="w-in" name="home_city" maxlength="80" value="${esc(p.home_city || "")}" placeholder="${esc(t("homeCityPh"))}"></label>
      <label class="af"><span>${esc(t("curPref"))}</span><select class="w-in" name="currency">${CURRENCIES.map((c) => `<option${(p.currency || "USD") === c ? " selected" : ""}>${c}</option>`).join("")}</select></label>
    </div>
    <span class="af-lbl">${esc(t("intPref"))}</span>
    <div class="chipset" id="profInts">${INTERESTS.map(([k, e]) => `<button type="button" class="pchip${mine.has(k) ? " on" : ""}" data-int="${k}"><span>${e}</span>${esc(t(`int.${k}`))}</button>`).join("")}</div>
    <p class="af-err" data-for="prof"></p>
    <button class="btn primary" type="submit">${esc(t("save"))}</button></form>

  <form class="d-card" id="passForm" novalidate><h2>${esc(t("passT"))}</h2>
    <div class="d-grid">
      <label class="af"><span>${esc(t("curPass"))}</span><input class="w-in" type="password" name="current" autocomplete="current-password" dir="ltr"></label>
      <span></span>
      <label class="af"><span>${esc(t("newPass"))}</span><input class="w-in" type="password" name="new" autocomplete="new-password" dir="ltr"></label>
      <label class="af"><span>${esc(t("newPass2"))}</span><input class="w-in" type="password" name="new2" autocomplete="new-password" dir="ltr"></label>
    </div>
    <p class="af-err" data-for="pass"></p>
    <button class="btn" type="submit">${esc(t("changePass"))}</button></form>

  <div class="d-card d-row"><button type="button" class="btn" data-dash="signout">
    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15 4h4v16h-4M10 8l-4 4 4 4M6 12h10" /></svg>${esc(t("signOut"))}</button></div>

  <form class="d-card danger-zone" id="delForm" novalidate><h2>${esc(t("dangerT"))}</h2><p>${esc(t("dangerP"))}</p>
    <label class="af"><span>${esc(t("delAccQ"))}</span><input class="w-in" type="password" name="password" autocomplete="current-password" dir="ltr"></label>
    <p class="af-err" data-for="del"></p>
    <button class="btn danger" type="submit">${esc(t("delAcc"))}</button></form>`;
}

function formErr(form, key, msg) { const el = form.querySelector(`.af-err[data-for="${key}"]`); if (el) el.textContent = msg || ""; }

async function onDashSubmit(e) {
  const form = e.target;
  if (!["profForm", "passForm", "delForm"].includes(form.id)) return;
  e.preventDefault();
  const f = new FormData(form);
  const btn = form.querySelector("button[type=submit]");
  btn.disabled = true;
  try {
    if (form.id === "profForm") {
      formErr(form, "prof", "");
      const interests = [...form.querySelectorAll("#profInts .pchip.on")].map((b) => b.dataset.int);
      if (!String(f.get("name")).trim()) { formErr(form, "prof", t("eName")); return; }
      const r = await api("/api/me", { method: "PATCH", body: { name: f.get("name"), home_city: f.get("home_city"), currency: f.get("currency"), interests } });
      account.user = r.user; dashData.user = r.user;
      renderAcctBtn();
      app.applyPrefs?.(r.user.prefs || {}, true);
      toast(t("saved"));
      loadForYou();
    } else if (form.id === "passForm") {
      formErr(form, "pass", "");
      const nw = String(f.get("new")), n2 = String(f.get("new2"));
      const pp = passwordProblem(nw);
      if (pp) { formErr(form, "pass", pp); return; }
      if (nw !== n2) { formErr(form, "pass", t("eMatch")); return; }
      await api("/api/me/password", { method: "POST", body: { current: f.get("current"), new: nw } });
      form.reset();
      toast(t("passChanged"));
    } else {
      formErr(form, "del", "");
      await api("/api/me", { method: "DELETE", body: { password: f.get("password") } });
      account.user = null;
      renderAcctBtn();
      closeDash();
      app.newTrip();
      toast(t("accDeleted"));
      loadForYou();
    }
  } catch (err) {
    formErr(form, form.id === "profForm" ? "prof" : form.id === "passForm" ? "pass" : "del", localError(err));
  } finally { btn.disabled = false; }
}

async function onDashClick(e) {
  const chip = e.target.closest(".pchip[data-int]");
  if (chip) { chip.classList.toggle("on"); return; }
  const filter = e.target.closest("[data-filter]");
  if (filter) { tripFilter = filter.dataset.filter; renderDash(); return; }
  const open = e.target.closest("[data-open]");
  if (open) { closeDash(); app.openTrip(open.dataset.open); return; }
  const act = e.target.closest("[data-dash]");
  if (act) {
    const a = act.dataset.dash;
    if (a === "new") { closeDash(); app.newTrip(); }
    else if (a === "signout") signOut();
    else if (a === "save-ints") {
      const interests = [...document.querySelectorAll("#coldInts .pchip.on")].map((b) => b.dataset.int);
      if (!interests.length) return;
      act.disabled = true;
      try { await api("/api/me", { method: "PATCH", body: { interests } }); await refreshDash(); loadForYou(); }
      finally { act.disabled = false; }
    }
    return;
  }
  const tb = e.target.closest("[data-trip]");
  if (tb) {
    const row = tb.closest(".trip-row"), id = row.dataset.id;
    const k = tb.dataset.trip;
    if (k === "open") { closeDash(); app.openTrip(id); }
    else if (k === "ask") { row.querySelector(".tr-confirm").hidden = false; row.querySelector(".tr-act").hidden = true; }
    else if (k === "keep") { row.querySelector(".tr-confirm").hidden = true; row.querySelector(".tr-act").hidden = false; }
    else if (k === "del") {
      tb.disabled = true;
      try {
        await api(`/api/trips/${encodeURIComponent(id)}`, { method: "DELETE" });
        row.classList.add("gone");
        app.tripDeleted?.(id);
        toast(t("tripDeleted"));
        setTimeout(refreshDash, 300);
      } catch (err) { toast(localError(err)); tb.disabled = false; }
    }
  }
}

// ------------------------------------------------------------------ hooks for app.js
/** A trip was just planned: nudge guests to keep it (once per trip) and refresh the picks. */
export function onTripPlanned(trip) {
  loadForYou();
  if (account.user || !trip) return;
  const key = `nudged:${trip.trip_id}`;
  try { if (sessionStorage.getItem(key)) return; sessionStorage.setItem(key, "1"); } catch (_) { /* storage unavailable */ }
  setTimeout(() => toast(t("guestNudge"), { label: t("guestNudgeGo"), run: () => openAuth("signup") }), 1800);
}

export function refreshAccountLanguage() {
  renderAcctBtn();
  if ($("authWrap") && !$("authWrap").hidden) {  // created lazily: refresh its static labels too
    $("authWrap").querySelectorAll("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n); });
    renderAuth();
  }
  if (!$("dash").hidden) renderDash();
  if (!$("forYou").hidden) loadForYou();
}

export async function initAccount(hooks) {
  app = hooks;
  renderAcctBtn();
  $("acctBtn").addEventListener("click", () => (account.user ? openDash() : openAuth("signin")));
  $("dashBack").addEventListener("click", closeDash);
  $("dashTabs").addEventListener("click", (e) => {
    const b = e.target.closest("[data-tab]");
    if (!b) return;
    dashTab = b.dataset.tab; renderDash(); $("dash").scrollTo({ top: 0 });
  });
  $("dashBody").addEventListener("click", onDashClick);
  $("dashBody").addEventListener("submit", onDashSubmit);
  $("forYouAll").addEventListener("click", () => (account.user ? openDash() : openAuth("signup", t("fyReason"), () => openDash())));
  try {
    const r = await api("/api/auth/me");
    account.user = r.user;
    if (r.user) app.applyPrefs?.(r.user.prefs || {});
  } catch (_) { account.user = null; }
  renderAcctBtn();
  loadForYou();
}
