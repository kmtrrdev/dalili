// The landmark camera: a photo -> the place it shows (checked against Wikipedia on the server) -> a guide written from
// its article, which the traveller can question. The photo is resized here and only read by the server, never stored.
import { extend, getLang, locale, t } from "./i18n.js";
import { esc } from "./account.js";

extend({
  en: {
    lmOpen: "What's this place? Recognise it from a photo", lmShort: "Photo",
    lmLooking: "Looking at your photo…", lmChecking: "Checking it with Wikipedia…", lmWriting: "Writing your guide…",
    lmHistory: "History", lmTips: "Visiting tips", lmAskPh: "Ask anything about this place…",
    lmPlan: "Plan a trip here", lmAgain: "Another photo", lmWiki: "Wikipedia",
    lmConf: { high: "Recognised", medium: "Probably", low: "Best guess" },
    lmUnclear: "I couldn't recognise a landmark in this photo. Try a clearer shot of the whole place, in daylight if you can.",
    lmUnverified: (g) => `It may be ${g}, but I couldn't confirm it - so I won't guess. Try another angle.`,
    lmUnavailable: "Recognition isn't available right now. Please try again in a moment.",
    lmErr: "Couldn't read this photo. Try another one.",
    lmPrivacy: "Your photo is only read to recognise the place - it isn't stored.",
    lmPlanMsg: (name, place) => `Plan a trip to ${place} - I want to see ${name}`,
  },
  ar: {
    lmOpen: "إيه المكان ده؟ صوّره وأنا أعرّفك عليه", lmShort: "صورة",
    lmLooking: "ببص على صورتك…", lmChecking: "بتأكد منه في ويكيبيديا…", lmWriting: "بكتبلك الدليل…",
    lmHistory: "تاريخه", lmTips: "نصايح للزيارة", lmAskPh: "اسأل أي حاجة عن المكان ده…",
    lmPlan: "خطّطلي رحلة هنا", lmAgain: "صورة تانية", lmWiki: "ويكيبيديا",
    lmConf: { high: "اتعرّفت عليه", medium: "غالباً", low: "أقرب تخمين" },
    lmUnclear: "معرفتش أتعرّف على معلم في الصورة دي. جرّب صورة أوضح للمكان كله، في النور لو تقدر.",
    lmUnverified: (g) => `ممكن يكون ${g}، بس معرفتش أتأكد - فمش هخمّن. جرّب من زاوية تانية.`,
    lmUnavailable: "التعرّف على الصور مش متاح دلوقتي. جرّب كمان شوية.",
    lmErr: "معرفتش أقرا الصورة دي. جرّب صورة تانية.",
    lmPrivacy: "صورتك بتتقري بس عشان نعرف المكان - مش بتتحفظ.",
    lmPlanMsg: (name, place) => `عايز أسافر ${place} - نفسي أشوف ${name}`,
  },
});

const MAX_SIDE = 1280;
let app = null;      // hooks from app.js: modal, closeModal, md (markdown), send (a new trip)
let current = null;  // the recognised landmark
let history = [];

function countryName(cc) {
  try { return new Intl.DisplayNames([locale()], { type: "region" }).of(cc) || cc; } catch (_) { return cc; }
}
const ar = () => getLang() === "ar";
const dir = () => (ar() ? "rtl" : "ltr");  // the guide is written in the page's language

/** The photo as a JPEG data URL, longest side MAX_SIDE (phone photos are often 4000 px and several MB). */
async function shrink(file) {
  const bmp = await createImageBitmap(file, { imageOrientation: "from-image" });
  const k = Math.min(1, MAX_SIDE / Math.max(bmp.width, bmp.height));
  const c = document.createElement("canvas");
  c.width = Math.round(bmp.width * k); c.height = Math.round(bmp.height * k);
  c.getContext("2d").drawImage(bmp, 0, 0, c.width, c.height);
  return c.toDataURL("image/jpeg", 0.85);
}

function pick() {
  const input = document.createElement("input");
  input.type = "file";
  input.accept = "image/*";  // phones offer the camera or the gallery
  input.addEventListener("change", () => { if (input.files && input.files[0]) run(input.files[0]); });
  input.click();
}

async function run(file) {
  const box = app.modal(`<div class="lm-photo"><span class="lm-scan"></span></div>
    <div class="modal-body lm-wait"><span class="spinner"></span><b id="lmStep">${t("lmLooking")}</b>
    <p class="muted">${t("lmPrivacy")}</p></div>`);
  box.classList.add("lm");
  let image;
  try { image = await shrink(file); } catch (_) { return failed(box, t("lmErr")); }
  box.querySelector(".lm-photo").style.backgroundImage = `url("${image}")`;
  const steps = [t("lmChecking"), t("lmWriting")];
  const timer = setInterval(() => { const s = box.querySelector("#lmStep"); if (s && steps.length) s.textContent = steps.shift(); }, 4500);
  let out;
  try {
    const r = await fetch("/api/landmarks/identify", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ image, lang: getLang() }) });
    out = r.ok ? await r.json() : { found: false, reason: r.status === 429 ? "unavailable" : "error" };
  } catch (_) { out = { found: false, reason: "unavailable" }; }
  clearInterval(timer);
  if (!box.isConnected) return;  // closed meanwhile
  if (!out.found) {
    const why = out.reason === "unclear" ? t("lmUnclear") : out.reason === "unverified" ? t("lmUnverified", out.guess || "")
      : out.reason === "error" ? t("lmErr") : t("lmUnavailable");
    return failed(box, why);
  }
  current = out;
  history = [];
  render(box, image);
}

function failed(box, text) {
  box.querySelector(".modal-body").outerHTML = `<div class="modal-body"><p class="lm-fail">${esc(text)}</p>
    <div class="modal-links"><button class="btn primary" type="button" data-lm="again">📷 ${t("lmAgain")}</button></div></div>`;
  box.querySelector('[data-lm="again"]').addEventListener("click", pick);
}

function render(box, image) {
  const l = current, g = l.guide || {};
  const name = g.name || (ar() && l.name_ar) || l.name;
  const place = [l.city, countryName(l.country_code)].filter(Boolean).join(ar() ? "، " : ", ");
  box.innerHTML = `<button class="icon-btn modal-x" type="button" aria-label="${t("close")}">✕</button>
    <div class="lm-photo lm-done" style="background-image:url('${esc(l.image || image)}')">
      <span class="lm-conf ${esc(l.confidence)}">${esc(t("lmConf")[l.confidence] || "")}</span>
      <img class="lm-yours" src="${image}" alt=""></div>
    <div class="modal-body">
      <h3 dir="${dir()}">${esc(name)}</h3><p class="muted">📍 ${esc(place)}</p>
      <p dir="${dir()}">${esc(g.summary || "")}</p>
      ${g.history?.length ? `<h4>${t("lmHistory")}</h4><ul class="lm-list">${g.history.map((x) => `<li dir="${dir()}">${esc(x)}</li>`).join("")}</ul>` : ""}
      ${g.tips?.length ? `<h4>${t("lmTips")}</h4><ul class="lm-list">${g.tips.map((x) => `<li dir="${dir()}">${esc(x)}</li>`).join("")}</ul>` : ""}
      <div class="lm-chat"><div class="lm-msgs" id="lmMsgs"></div>
        <div class="lm-chips" id="lmChips">${(g.questions || []).map((q) => `<button class="chip ai" type="button" dir="auto">${esc(q)}</button>`).join("")}</div>
        <form class="qc lm-ask" id="lmAsk"><textarea rows="1" dir="auto" maxlength="500" placeholder="${esc(t("lmAskPh"))}"></textarea>
          <button class="qc-send" type="submit" aria-label="${t("send")}"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 12l16-8-6 16-2.5-6.5z" /></svg></button></form></div>
      <div class="modal-links">
        <button class="btn primary" type="button" data-lm="plan">✈ ${t("lmPlan")}</button>
        <a class="btn" href="${esc(l.wikipedia)}" target="_blank" rel="noopener">${t("lmWiki")}</a>
        <button class="btn ghost" type="button" data-lm="again">📷 ${t("lmAgain")}</button></div>
    </div>`;
  box.querySelector(".modal-x").addEventListener("click", app.closeModal);
  box.querySelector('[data-lm="again"]').addEventListener("click", pick);
  box.querySelector('[data-lm="plan"]').addEventListener("click", () => {
    app.closeModal();
    app.send(t("lmPlanMsg", name, l.city ? `${l.city}, ${countryName(l.country_code)}` : countryName(l.country_code)));
  });
  box.querySelector("#lmChips").addEventListener("click", (e) => {
    const b = e.target.closest(".chip");
    if (b) ask(box, b.textContent);
  });
  const form = box.querySelector("#lmAsk"), field = form.querySelector("textarea");
  form.addEventListener("submit", (e) => { e.preventDefault(); const q = field.value.trim(); if (q) { field.value = ""; ask(box, q); } });
  field.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); } });
}

async function ask(box, question) {
  const msgs = box.querySelector("#lmMsgs");
  const bubble = (role, html) => {
    const d = document.createElement("div");
    d.className = `msg ${role}`; d.dir = "auto"; d.innerHTML = html;
    msgs.appendChild(d); d.scrollIntoView({ block: "nearest" });
    return d;
  };
  bubble("user", esc(question));
  const wait = bubble("assistant typing", "<i></i><i></i><i></i>");
  let out = null;
  try {
    const r = await fetch("/api/landmarks/ask", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: current.name, question, history, lang: getLang() }) });
    if (r.ok) out = await r.json();
  } catch (_) { /* shown below */ }
  wait.remove();
  if (!box.isConnected) return;
  bubble("assistant", out ? app.md(out.answer) : esc(t("lmUnavailable")));
  history.push({ role: "user", text: question }, { role: "assistant", text: out ? out.answer : "" });
  if (out?.follow_ups?.length) {
    box.querySelector("#lmChips").innerHTML = out.follow_ups.map((q) => `<button class="chip ai" type="button" dir="auto">${esc(q)}</button>`).join("");
  }
}

export function initLandmarks(hooks) {
  app = hooks;
  document.querySelectorAll("[data-landmark]").forEach((b) => b.addEventListener("click", pick));
}
