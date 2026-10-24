// The "Travel buddies" tab of a trip: who else is in the same city at the same time, a small group chat once you join
// (signed-in only), meet-up ideas from the members' own plans, and report / block on every message. The chat is polled
// every few seconds while it is open (it works the same across several server instances).
import { extend, locale, t } from "./i18n.js";
import { esc, openAuth } from "./account.js";

extend({
  en: {
    bdIntro: "Travelling without friends this time? Meet people who'll be in the same city at the same time - a small group chat, matched by your dates and interests.",
    bdPeople: (n) => (n === 1 ? "1 traveller there around your dates" : `${n} travellers there around your dates`),
    bdFirst: "No one yet - join and you'll meet the travellers who come next.",
    bdWomen: (n) => `${n} in women-only groups`, bdShare: "You share", bdJoin: "Join the group", bdOpen: "Open the chat",
    bdWomenOnly: "Women-only group (self-declared)", bdSignIn: "Sign in to join", bdSignWhy: "Sign in to meet your travel buddies.",
    bdRules: "Only your first name, your dates in this city and your interests are shown - never your hotel or flights. Dalili may suggest meeting at a sight that is in two members' plans. Meet in public places, keep personal details to yourself, and report anything that feels wrong.",
    bdTogether: (n) => (n === 1 ? "1 day together" : `${n} days together`), bdYou: "you",
    bdIdeas: "Ideas to meet", bdPh: "Write to the group…", bdLeave: "Leave the group", bdLeaveQ: "Leave this group?",
    bdReport: "Report", bdBlock: (n) => `Block ${n}`, bdReported: "Thanks - we'll look at it.", bdBlocked: "Blocked. You won't see their messages.",
    bdErr: "Couldn't load the group - try again.", bdFast: "You're sending messages very fast - wait a moment.",
    bdBack: "All cities", bdEmpty: "Say hello 👋 - you're the first here.",
    bdSafe: "Meet in public places · tap ⋯ on a message to report or block",
  },
  ar: {
    bdIntro: "مسافر لوحدك المرة دي؟ اتعرّف على ناس هتكون في نفس المدينة في نفس الوقت - جروب صغير، على حسب مواعيدك واهتماماتك.",
    bdPeople: (n) => (n === 1 ? "مسافر واحد هناك في نفس مواعيدك" : `${n} مسافرين هناك في نفس مواعيدك`),
    bdFirst: "لسه مفيش حد - ادخل وهتتعرّف على اللي جايين بعدك.",
    bdWomen: (n) => `${n} في جروبات للسيدات بس`, bdShare: "مشتركين في", bdJoin: "ادخل الجروب", bdOpen: "افتح الشات",
    bdWomenOnly: "جروب للسيدات بس (بإقرارك)", bdSignIn: "سجّل دخول عشان تنضم", bdSignWhy: "سجّل دخولك عشان تقابل رفقاء سفرك.",
    bdRules: "بيظهر اسمك الأول بس، ومواعيدك في المدينة دي، واهتماماتك - عمر ما بيظهر فندقك أو طيرانك. دليلي ممكن يقترح تتقابلوا عند مكان موجود في برنامج اتنين منكم. اتقابلوا في أماكن عامة، خلّي بياناتك الشخصية لنفسك، وبلّغ عن أي حاجة مش مريحة.",
    bdTogether: (n) => (n === 1 ? "يوم مع بعض" : `${n} أيام مع بعض`), bdYou: "انت",
    bdIdeas: "أفكار للقاء", bdPh: "اكتب للجروب…", bdLeave: "اخرج من الجروب", bdLeaveQ: "تخرج من الجروب ده؟",
    bdReport: "بلّغ", bdBlock: (n) => `احظر ${n}`, bdReported: "شكراً - هنراجعها.", bdBlocked: "اتحظر. مش هتشوف رسايله.",
    bdErr: "معرفتش أحمّل الجروب - جرّب تاني.", bdFast: "بتبعت رسايل بسرعة قوي - استنى لحظة.",
    bdBack: "كل المدن", bdEmpty: "قول أهلاً 👋 - انت أول واحد هنا.",
    bdSafe: "اتقابلوا في أماكن عامة · دوس ⋯ على أي رسالة عشان تبلّغ أو تحظر",
  },
});

const POLL_MS = 3000;
let box = null;       // the tab's panel
let trip = null;
let group = null;     // the open group
let lastId = 0;
let timer = null;

const day = (iso, o = { day: "numeric", month: "short" }) => new Date(`${iso}T12:00:00`).toLocaleDateString(locale(), o);
const live = () => box && box.isConnected && box.querySelector("#bdChat");

function stop() { clearTimeout(timer); timer = null; }

async function api(path, body) {
  const r = await fetch(path, body === undefined ? { credentials: "same-origin" } : {
    method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!r.ok) { const e = new Error(r.status); e.status = r.status; throw e; }
  return r.json();
}

async function preview() {
  stop();
  group = null;
  box.innerHTML = `<div class="d-loading"><span class="spinner"></span></div>`;
  let d;
  try { d = await api(`/api/buddies/preview?trip_id=${encodeURIComponent(trip.trip_id)}`); } catch (_) { box.innerHTML = `<p class="muted">${t("bdErr")}</p>`; return; }
  box.innerHTML = `<div class="bd"><p class="bd-intro">👥 ${t("bdIntro")}</p>
    ${d.cities.map((c) => `<div class="card bd-city">
      <div class="bd-head"><b>📍 ${esc(c.city)}</b><span class="muted">${day(c.start)} – ${day(c.end)}</span></div>
      <p class="bd-count">${c.travellers ? t("bdPeople", c.travellers) : t("bdFirst")}${c.women_only ? ` · ${t("bdWomen", c.women_only)}` : ""}</p>
      ${c.shared_interests.length ? `<div class="bd-tags"><small>${t("bdShare")}:</small>${c.shared_interests.map((i) => `<span class="rec-tag">${esc(i)}</span>`).join("")}</div>` : ""}
      ${c.group_id ? `<button class="btn primary small" type="button" data-open="${esc(c.group_id)}">💬 ${t("bdOpen")}</button>`
        : d.signed_in ? `<label class="switch bd-women"><input type="checkbox" data-women="${c.stop}"><i></i><span>${t("bdWomenOnly")}</span></label>
          <button class="btn primary small" type="button" data-join="${c.stop}">${t("bdJoin")}</button>`
        : `<button class="btn primary small" type="button" data-signin>${t("bdSignIn")}</button>`}
    </div>`).join("")}
    <p class="bd-rules">🛡️ ${t("bdRules")}</p></div>`;
  box.querySelectorAll("[data-open]").forEach((b) => b.addEventListener("click", () => open(b.dataset.open)));
  box.querySelectorAll("[data-join]").forEach((b) => b.addEventListener("click", () => join(+b.dataset.join, box.querySelector(`[data-women="${b.dataset.join}"]`)?.checked)));
  box.querySelectorAll("[data-signin]").forEach((b) => b.addEventListener("click", () => openAuth("signin", t("bdSignWhy"), () => preview())));
}

async function join(stopIndex, womenOnly) {
  try {
    const r = await api("/api/buddies/join", { trip_id: trip.trip_id, stop: stopIndex, women_only: !!womenOnly });
    open(r.group_id);
  } catch (e) { if (e.status === 401) openAuth("signin", t("bdSignWhy"), () => preview()); else box.insertAdjacentHTML("beforeend", `<p class="muted">${t("bdErr")}</p>`); }
}

function members(list) {
  return list.map((m) => `<span class="bd-member${m.you ? " you" : ""}" title="${esc(m.interests.join(", "))}">
    <i>${esc(m.name[0] || "?")}</i>${esc(m.name)}${m.you ? ` (${t("bdYou")})` : ` · ${t("bdTogether", m.days_together)}`}</span>`).join("");
}

function bubble(m) {
  if (m.kind === "system") return `<div class="bd-sys" dir="auto">${esc(m.text)}</div>`;
  const time = new Date(m.at).toLocaleTimeString(locale(), { hour: "2-digit", minute: "2-digit" });
  return `<div class="msg ${m.mine ? "user" : "assistant"} bd-msg" data-id="${m.id}" data-user="${esc(m.user)}" data-name="${esc(m.name)}" dir="auto">
    ${m.mine ? "" : `<b class="bd-who">${esc(m.name)}</b>`}${esc(m.text)}<small class="bd-time">${time}</small>
    ${m.mine ? "" : `<button class="bd-more" type="button" aria-label="⋯">⋯</button>`}</div>`;
}

function append(messages) {
  const list = box.querySelector("#bdMsgs");
  if (!list || !messages.length) return;
  list.querySelector(".bd-empty")?.remove();
  const near = list.scrollHeight - list.scrollTop - list.clientHeight < 80;
  list.insertAdjacentHTML("beforeend", messages.map(bubble).join(""));
  lastId = Math.max(lastId, ...messages.map((m) => m.id));
  if (near) list.scrollTop = list.scrollHeight;
}

async function open(gid) {
  stop();
  lastId = 0;
  try { group = await api(`/api/buddies/groups/${encodeURIComponent(gid)}`); } catch (_) { box.innerHTML = `<p class="muted">${t("bdErr")}</p>`; return; }
  const g = group;
  box.innerHTML = `<div class="bd bd-chat-wrap" id="bdChat">
    <div class="bd-top"><button class="btn ghost small" type="button" id="bdBack">← ${t("bdBack")}</button>
      <b>💬 ${esc(g.city)}</b><span class="muted">${day(g.start)} – ${day(g.end)}${g.women_only ? " · 👭" : ""}</span></div>
    <div class="bd-members" id="bdMembers">${members(g.members)}</div>
    ${g.ideas?.length ? `<div class="bd-ideas"><b>✨ ${t("bdIdeas")}</b>${g.ideas.map((i) => `<p dir="auto">${esc(i)}</p>`).join("")}</div>` : ""}
    <div class="bd-msgs" id="bdMsgs">${g.messages.length ? "" : `<p class="bd-empty muted">${t("bdEmpty")}</p>`}</div>
    <form class="qc bd-form" id="bdForm"><textarea rows="1" dir="auto" maxlength="1000" placeholder="${esc(t("bdPh"))}"></textarea>
      <button class="qc-send" type="submit" aria-label="${t("send")}"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 12l16-8-6 16-2.5-6.5z" /></svg></button></form>
    <div class="bd-foot"><span class="muted">🛡️ ${t("bdSafe")}</span>
      <button class="btn ghost small" type="button" id="bdLeave">${t("bdLeave")}</button></div></div>`;
  append(g.messages);
  box.querySelector("#bdBack").addEventListener("click", preview);
  box.querySelector("#bdLeave").addEventListener("click", async () => {
    if (!confirm(t("bdLeaveQ"))) return;
    await api(`/api/buddies/groups/${encodeURIComponent(g.id)}/leave`, {});
    preview();
  });
  const form = box.querySelector("#bdForm"), field = form.querySelector("textarea");
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = field.value.trim();
    if (!text) return;
    field.value = "";
    try { await api(`/api/buddies/groups/${encodeURIComponent(g.id)}/messages`, { text }); await poll(true); }
    catch (err) { field.value = text; if (err.status === 429) box.querySelector("#bdMsgs").insertAdjacentHTML("beforeend", `<p class="bd-sys">${t("bdFast")}</p>`); }
  });
  field.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); } });
  box.querySelector("#bdMsgs").addEventListener("click", menu);
  timer = setTimeout(poll, POLL_MS);
}

async function poll(once = false) {
  if (!live() || !group) return stop();
  try {
    const d = await api(`/api/buddies/groups/${encodeURIComponent(group.id)}?after=${lastId}`);
    append(d.messages);
    if (d.members.length !== group.members.length && box.querySelector("#bdMembers")) {  // someone joined or left
      group.members = d.members;
      box.querySelector("#bdMembers").innerHTML = members(d.members);
    }
  } catch (_) { /* a missed poll: the next one catches up */ }
  if (!once) timer = setTimeout(poll, POLL_MS);
}

function menu(e) {
  const btn = e.target.closest(".bd-more");
  if (!btn) return;
  const msg = btn.closest(".bd-msg");
  msg.querySelector(".bd-menu")?.remove();
  msg.insertAdjacentHTML("beforeend", `<span class="bd-menu"><button type="button" data-act="report">🚩 ${t("bdReport")}</button>
    <button type="button" data-act="block">⛔ ${esc(t("bdBlock", msg.dataset.name))}</button></span>`);
  msg.querySelector(".bd-menu").addEventListener("click", async (ev) => {
    const act = ev.target.closest("[data-act]")?.dataset.act;
    if (!act) return;
    if (act === "report") {
      await api(`/api/buddies/messages/${msg.dataset.id}/report`, { reason: "reported" });
      msg.querySelector(".bd-menu").textContent = t("bdReported");
    } else {
      await api("/api/buddies/block", { user_id: msg.dataset.user });
      box.querySelectorAll(`.bd-msg[data-user="${CSS.escape(msg.dataset.user)}"]`).forEach((x) => x.remove());
      box.querySelector("#bdMsgs").insertAdjacentHTML("beforeend", `<p class="bd-sys">${t("bdBlocked")}</p>`);
    }
  });
}

/** Called by app.js when the tab is shown. */
export function mountBuddies(el, tripObj) {
  box = el;
  trip = tripObj;
  if (!trip || !trip.trip_id) return;
  preview();
}
