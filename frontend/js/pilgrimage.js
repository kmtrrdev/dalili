// The Hajj & Umrah page: the rituals step by step, the miqat, prayer times in Makkah and Madinah, a checklist - and a
// short form that hands an Umrah to the planner. The guidance is fixed text (never written by the model), drawn from
// the widely followed practice published by the Saudi Ministry of Hajj and Umrah; it points to a scholar for rulings.
import { extend, getLang, locale, t } from "./i18n.js";
import { esc } from "./account.js";

const NUSUK = "https://www.nusuk.sa";
const MINISTRY = "https://www.haj.gov.sa";

extend({
  en: {
    pgNav: "Hajj & Umrah", pgTitle: "Hajj & Umrah",
    pgSub: "The rituals step by step, the miqat, prayer times in Makkah and Madinah, what to prepare - and an Umrah planned around the prayers, with a hotel close to the Haram.",
    pgNote: "General guidance following the widely published practice (Saudi Ministry of Hajj and Umrah, Nusuk). For a ruling about your own case, ask a scholar you trust.",
    pgTabs: { umrah: "Umrah", hajj: "Hajj", miqat: "Miqat", prayers: "Prayer times", check: "Checklist" },
    pgPlanT: "Plan my Umrah", pgPlanS: "Flights, a hotel near the Haram, the Umrah on your first day in Makkah, the Prophet's Mosque in Madinah, and the prayer times on every day.",
    pgFrom: "Flying from", pgStart: "Departure", pgNights: "Nights", pgMakkah: "in Makkah", pgPax: "Travellers", pgBudget: "Total budget",
    pgGo: "Plan my Umrah", pgFill: "Add where you fly from and the departure date.",
    pgMsg: (n, mk, md, date, pax, budget, from) => `I want to do Umrah: ${n} nights from ${date} (${mk} in Makkah${md ? `, ${md} in Madinah` : ""}) for ${pax} traveller${pax > 1 ? "s" : ""}${budget ? `, budget ${budget}` : ""}, flying from ${from}`,
    pgHomeT: "Hajj & Umrah", pgHomeS: "The rituals step by step, prayer times, the miqat - and an Umrah planned for you.", pgOpen: "Open the guide",
    pgCity: { makkah: "Makkah", madinah: "Madinah" }, pgDate: "From", pgPrayer: ["Fajr", "Dhuhr", "Asr", "Maghrib", "Isha"],
    pgMethod: "Umm al-Qura method, as used in the two Holy Mosques.", pgLoading: "Loading…", pgErr: "Couldn't load right now - try again.",
    pgHajjDates: (y) => `Expected dates of Hajj ${y} AH`, pgHajjNote: "By the Umm al-Qura calendar; the moon sighting can move them by a day.",
    pgDay: (d) => `${d} Dhu al-Hijjah`, pgLinks: "Official sources",
  },
  ar: {
    pgNav: "الحج والعمرة", pgTitle: "الحج والعمرة",
    pgSub: "المناسك خطوة بخطوة، المواقيت، مواقيت الصلاة في مكة والمدينة، وتجهّز إيه - وعمرة متخططة حوالين الصلوات، بفندق قريب من الحرم.",
    pgNote: "إرشادات عامة على المعمول به والمنشور (وزارة الحج والعمرة السعودية، منصة نسك). لحكم يخص حالتك، اسأل عالم تثق فيه.",
    pgTabs: { umrah: "العمرة", hajj: "الحج", miqat: "المواقيت", prayers: "مواقيت الصلاة", check: "تجهيزات" },
    pgPlanT: "خطّطلي عمرة", pgPlanS: "طيران، فندق قريب من الحرم، العمرة في أول يوم في مكة، المسجد النبوي في المدينة، ومواقيت الصلاة كل يوم.",
    pgFrom: "مسافر من", pgStart: "تاريخ السفر", pgNights: "عدد الليالي", pgMakkah: "في مكة", pgPax: "عدد الأفراد", pgBudget: "الميزانية الكلية",
    pgGo: "خطّطلي العمرة", pgFill: "اكتب مسافر منين وتاريخ السفر.",
    pgMsg: (n, mk, md, date, pax, budget, from) => `عايز أعمل عمرة: ${n} ليالي من ${date} (${mk} في مكة${md ? ` و${md} في المدينة` : ""}) لـ ${pax} ${pax > 1 ? "أفراد" : "فرد"}${budget ? `، الميزانية ${budget}` : ""}، مسافر من ${from}`,
    pgHomeT: "الحج والعمرة", pgHomeS: "المناسك خطوة بخطوة، مواقيت الصلاة، المواقيت - وعمرة نخطّطهالك.", pgOpen: "افتح الدليل",
    pgCity: { makkah: "مكة المكرمة", madinah: "المدينة المنورة" }, pgDate: "من يوم", pgPrayer: ["الفجر", "الظهر", "العصر", "المغرب", "العشاء"],
    pgMethod: "بطريقة أم القرى، المعمول بها في الحرمين.", pgLoading: "بيحمّل…", pgErr: "معرفتش أحمّل دلوقتي - جرّب تاني.",
    pgHajjDates: (y) => `المواعيد المتوقعة لحج ${y} هـ`, pgHajjNote: "حسب تقويم أم القرى؛ رؤية الهلال ممكن تغيّرها يوم.",
    pgDay: (d) => `${d} ذو الحجة`, pgLinks: "مصادر رسمية",
  },
});

// Each step: [title, text] in English and Arabic.
const UMRAH = {
  en: [
    ["1 · Ihram at the miqat", "Before the miqat: a full wash (ghusl) and perfume on the body (not the clothes). Men wear two white unstitched sheets and leave the head uncovered; women wear their usual modest clothes, without a face veil (niqab) or gloves. Make the intention for Umrah - \"Labbayka Allahumma 'umrah\" - and repeat the talbiyah (\"Labbayk Allahumma labbayk…\") until the tawaf begins. In ihram: no cutting hair or nails, no perfume, no hunting, no marital relations; men don't wear stitched clothes or cover the head."],
    ["2 · Tawaf", "Enter Masjid al-Haram with the right foot and the mosque's supplication. Men uncover the right shoulder during this tawaf. Start at the Black Stone corner: touch or kiss it if you can easily, otherwise point to it and say \"Bismillah, Allahu akbar\". Walk seven circuits with the Kaaba on your left (men walk briskly in the first three if possible). Between the Yemeni corner and the Black Stone: \"Rabbana atina fid-dunya hasanah wa fil-akhirati hasanah wa qina 'adhaban-nar\". Any supplication or dhikr in your own words is fine."],
    ["3 · Prayer behind Maqam Ibrahim · Zamzam", "Pray two rak'ahs behind Maqam Ibrahim if there is room - anywhere in the mosque if it's crowded - then drink Zamzam water."],
    ["4 · Sa'i between Safa and Marwah", "Go up Safa, recite \"Innas-Safa wal-Marwata min sha'a'irillah\", face the Kaaba and supplicate. Walk to Marwah (men hurry between the green lights) - that is one lap; back to Safa is the second. Seven laps, ending at Marwah, supplicating as you walk."],
    ["5 · Shaving or trimming", "Men shave the head (preferred) or trim it all over; women cut about a fingertip's length from the end of their hair. Your Umrah is complete and the restrictions of ihram are lifted."],
  ],
  ar: [
    ["١ · الإحرام من الميقات", "قبل الميقات: الاغتسال والتطيّب في البدن (مش في ملابس الإحرام). الرجل يلبس إزار ورداء أبيضين غير مخيطين وراسه مكشوفة؛ والمرأة تلبس لبسها الساتر العادي من غير نقاب ولا قفازين. انوِ العمرة: «لبيك اللهم عمرة»، وكرّر التلبية («لبيك اللهم لبيك…») لحد ما تبدأ الطواف. في الإحرام: ممنوع قص الشعر والأظافر، والطيب، والصيد، والجماع؛ والرجل ما يلبسش مخيط وما يغطيش راسه."],
    ["٢ · الطواف", "ادخل المسجد الحرام برجلك اليمين وقول دعاء دخول المسجد. الرجل يكشف كتفه اليمين في الطواف ده (الاضطباع). ابدأ من ركن الحجر الأسود: استلمه أو قبّله لو سهل، وإلا شاور عليه وقول «بسم الله، الله أكبر». سبعة أشواط والكعبة على شمالك (والرجل يرمل في الأشواط التلاتة الأولى لو أمكن). بين الركن اليماني والحجر: «ربنا آتنا في الدنيا حسنة وفي الآخرة حسنة وقنا عذاب النار». ادعي واذكر بأي كلام من قلبك."],
    ["٣ · ركعتين خلف المقام · زمزم", "صلّي ركعتين خلف مقام إبراهيم لو في مكان - أو في أي حتة في المسجد لو زحمة - وبعدين اشرب من زمزم."],
    ["٤ · السعي بين الصفا والمروة", "اطلع الصفا واقرأ «إن الصفا والمروة من شعائر الله»، واستقبل الكعبة وادعي. امشي للمروة (والرجل يسرع بين العلمين الأخضرين) - ده شوط؛ والرجوع للصفا الشوط التاني. سبعة أشواط تخلص عند المروة، وادعي وانت ماشي."],
    ["٥ · الحلق أو التقصير", "الرجل يحلق شعره (وده الأفضل) أو يقصّره من كل الراس؛ والمرأة تقص قدر أنملة من أطراف شعرها. كده عمرتك تمت وتحللت من الإحرام."],
  ],
};

const HAJJ = {
  en: [
    ["The three ways", "Tamattu' (most pilgrims from abroad): an Umrah in the Hajj months, out of ihram, then ihram for Hajj on the 8th - a sacrifice is due. Qiran: Umrah and Hajj together in one ihram - a sacrifice is due. Ifrad: Hajj alone."],
    ["8 Dhu al-Hijjah · Tarwiyah", "Ihram for Hajj from where you are staying (for tamattu'), then to Mina: Dhuhr to Fajr prayed there, the four-rak'ah prayers shortened."],
    ["9 Dhu al-Hijjah · Arafah", "After sunrise, to Arafat - standing at Arafah is the heart of Hajj. Dhuhr and Asr combined and shortened, then supplication until sunset. After sunset, to Muzdalifah."],
    ["The night at Muzdalifah", "Maghrib and Isha combined; the night spent there; pebbles collected for the Jamarat."],
    ["10 Dhu al-Hijjah · the Day of Sacrifice (Eid)", "Stoning Jamarat al-Aqabah with seven pebbles, the sacrifice, shaving or trimming (the first release from ihram), and tawaf al-ifadah (with the sa'i for tamattu')."],
    ["11-13 Dhu al-Hijjah · the days of Tashreeq", "In Mina: after midday, stoning the three Jamarat - small, middle, then large - seven pebbles each. Leaving on the 12th before sunset is allowed."],
    ["Farewell tawaf", "The last act before leaving Makkah."],
    ["How to go", "Hajj is only through official channels: for Egyptians, the Ministry of Interior lottery, the Ministry of Social Solidarity or a licensed tourism company; for many other countries, the Nusuk Hajj platform. Dalili doesn't book Hajj."],
  ],
  ar: [
    ["الأنساك التلاتة", "التمتع (أغلب الحجاج من برّه): عمرة في أشهر الحج، تتحلل، وبعدين تحرم بالحج يوم ٨ - وعليك هدي. القِران: عمرة وحج بإحرام واحد - وعليك هدي. الإفراد: حج بس."],
    ["٨ ذو الحجة · يوم التروية", "الإحرام بالحج من مكانك (للمتمتع)، وبعدين على منى: الظهر لحد الفجر هناك، والرباعية تتقصر."],
    ["٩ ذو الحجة · يوم عرفة", "بعد الشروق على عرفات - والوقوف بعرفة هو ركن الحج الأعظم. الظهر والعصر جمع وقصر، ودعاء لحد المغرب. وبعد الغروب على مزدلفة."],
    ["ليلة مزدلفة", "المغرب والعشاء جمع، والمبيت هناك، ولقط الحصى للجمرات."],
    ["١٠ ذو الحجة · يوم النحر (العيد)", "رمي جمرة العقبة بسبع حصيات، والهدي، والحلق أو التقصير (التحلل الأول)، وطواف الإفاضة (ومعاه السعي للمتمتع)."],
    ["١١-١٣ ذو الحجة · أيام التشريق", "في منى: بعد الزوال رمي الجمرات التلاتة - الصغرى فالوسطى فالكبرى - سبع حصيات لكل واحدة. ويجوز التعجّل يوم ١٢ قبل المغرب."],
    ["طواف الوداع", "آخر حاجة قبل ما تمشي من مكة."],
    ["إزاي تروح", "الحج من القنوات الرسمية بس: للمصريين قرعة وزارة الداخلية، أو وزارة التضامن الاجتماعي، أو شركة سياحة مرخّصة؛ ولدول كتير تانية منصة نسك حج. دليلي ما بيحجزش الحج."],
  ],
};

const MIQAT = {
  en: [
    ["Dhul Hulayfah (Abyar Ali)", "For pilgrims coming from Madinah - about 420 km from Makkah."],
    ["Al-Juhfah (near Rabigh)", "For Egypt, the Levant, North Africa and those coming from the west - about 186 km."],
    ["Qarn al-Manazil (As-Sayl al-Kabir)", "For Najd, Taif and the Gulf by road - about 75 km."],
    ["Yalamlam (As-Sa'diyyah)", "For Yemen and the south - about 100 km."],
    ["Dhat 'Irq", "For Iraq and the north-east - about 100 km."],
    ["Flying in", "Enter ihram before the plane passes the miqat on your route (the crew usually announce it): put the ihram clothes on before boarding or on board. Flying to Madinah first? Your miqat is then Dhul Hulayfah, on the way to Makkah."],
    ["Already in Makkah?", "For another Umrah, go out to the nearest point outside the sanctuary - usually Masjid Aisha at Tan'eem - and enter ihram there."],
  ],
  ar: [
    ["ذو الحليفة (أبيار علي)", "للجاي من المدينة - حوالي ٤٢٠ كم من مكة."],
    ["الجحفة (قرب رابغ)", "لأهل مصر والشام والمغرب والجاي من الغرب - حوالي ١٨٦ كم."],
    ["قرن المنازل (السيل الكبير)", "لأهل نجد والطائف والخليج بالبر - حوالي ٧٥ كم."],
    ["يلملم (السعدية)", "لأهل اليمن والجنوب - حوالي ١٠٠ كم."],
    ["ذات عرق", "لأهل العراق والشمال الشرقي - حوالي ١٠٠ كم."],
    ["لو مسافر بالطيارة", "أحرم قبل ما الطيارة تعدّي الميقات اللي على طريقك (الطاقم عادة بيعلن): البس ملابس الإحرام قبل الطيارة أو جواها. لو نازل المدينة الأول، ميقاتك ذو الحليفة وانت رايح مكة."],
    ["لو انت في مكة أصلاً", "لعمرة تانية، اطلع لأقرب الحِل - عادة مسجد السيدة عائشة في التنعيم - وأحرم من هناك."],
  ],
};

const CHECK = {
  en: ["A passport valid for at least six months, and a visa that allows Umrah (many nationalities can use the tourist e-visa).",
    "Book your Umrah and your visit to Ar-Rawdah in the Nusuk app.",
    "Check the latest health requirements (vaccinations such as meningitis) on the official Saudi sources before you travel.",
    "Men: two white ihram sheets and a belt. Everyone: unscented soap and toiletries for the days in ihram.",
    "Comfortable sandals, a small bag for your shoes in the mosque, a light prayer mat.",
    "Water bottle, unscented sunscreen, an umbrella for the sun, your usual medicines.",
    "Some Saudi riyals in cash for small expenses.",
    "Modest clothes; phone on silent in the mosques; patience in the crowds - never push at the Black Stone."],
  ar: ["جواز سفر صالح ٦ شهور على الأقل، وتأشيرة تسمح بالعمرة (جنسيات كتير تقدر تستخدم التأشيرة السياحية الإلكترونية).",
    "احجز العمرة وزيارة الروضة من تطبيق نسك.",
    "اتأكد من آخر الاشتراطات الصحية (تطعيمات زي الحمى الشوكية) من المصادر السعودية الرسمية قبل السفر.",
    "للرجال: قطعتين إحرام بيض وحزام. للكل: صابون ومستلزمات من غير ريحة لأيام الإحرام.",
    "شبشب مريح، شنطة صغيرة للجزمة جوه المسجد، سجادة صلاة خفيفة.",
    "زجاجة مية، واقي شمس من غير ريحة، شمسية للشمس، أدويتك المعتادة.",
    "شوية ريال سعودي كاش للمصاريف الصغيرة.",
    "لبس محتشم، الموبايل صامت في المساجد، والصبر في الزحمة - وما تزقّش عند الحجر الأسود."],
};

const $ = (id) => document.getElementById(id);
let app = null;   // hooks from app.js: send (a new trip), beforeOpen
let tab = "umrah";
const lang = () => (getLang() === "ar" ? "ar" : "en");

function steps(list) {
  return `<ol class="pg-steps">${list.map(([h, p]) => `<li><b>${esc(h)}</b><p>${esc(p)}</p></li>`).join("")}</ol>`;
}

function planForm() {
  const today = new Date(Date.now() + 14 * 864e5).toISOString().slice(0, 10);
  return `<form class="pg-plan" id="pgForm"><div><b>🕋 ${t("pgPlanT")}</b><p class="muted">${t("pgPlanS")}</p></div>
    <div class="pg-fields">
      <label><span>${t("pgFrom")}</span><input name="from" class="w-in" autocomplete="off" placeholder="Cairo"></label>
      <label><span>${t("pgStart")}</span><input name="start" type="date" class="w-in" value="${today}"></label>
      <label><span>${t("pgNights")}</span><input name="nights" type="number" min="2" max="30" value="7" class="w-in"></label>
      <label><span>${t("pgMakkah")}</span><input name="makkah" type="number" min="1" max="30" value="5" class="w-in"></label>
      <label><span>${t("pgPax")}</span><input name="pax" type="number" min="1" max="9" value="2" class="w-in"></label>
      <label><span>${t("pgBudget")}</span><input name="budget" class="w-in" placeholder="2,500 USD"></label>
    </div>
    <p class="if-err" id="pgErr" hidden></p>
    <button class="btn primary" type="submit">${t("pgGo")}</button></form>`;
}

async function prayers() {
  const box = $("pgPrayers");
  const city = $("pgCitySel").value, start = $("pgDateSel").value;
  box.innerHTML = `<p class="muted">${t("pgLoading")}</p>`;
  try {
    const r = await fetch(`/api/pilgrimage/prayer-times?city=${city}&start=${start}&days=7`);
    if (!r.ok) throw new Error(r.status);
    const d = await r.json();
    const names = t("pgPrayer");
    box.innerHTML = `<div class="pg-table" role="table"><div class="pg-row pg-h" role="row"><span></span>${names.map((n) => `<span>${n}</span>`).join("")}</div>
      ${Object.entries(d.days).map(([iso, v]) => `<div class="pg-row" role="row"><span><b>${new Date(`${iso}T12:00:00`).toLocaleDateString(locale(), { weekday: "short", day: "numeric", month: "short" })}</b>
        <small>${v.hijri.day} ${esc(lang() === "ar" ? v.hijri.month_ar : v.hijri.month_en)}</small></span>
        ${["Fajr", "Dhuhr", "Asr", "Maghrib", "Isha"].map((k) => `<span>${v.times[k]}</span>`).join("")}</div>`).join("")}</div>
      <p class="muted pg-small">${t("pgMethod")}</p>`;
  } catch (_) { box.innerHTML = `<p class="muted">${t("pgErr")}</p>`; }
}

async function hajjDates() {
  const box = $("pgHajjDates");
  try {
    const r = await fetch("/api/pilgrimage/hajj-dates");
    if (!r.ok) throw new Error(r.status);
    const d = await r.json();
    box.innerHTML = `<b>${t("pgHajjDates", d.hijri_year)}</b><ul>${Object.entries(d.days).map(([day, iso]) => `<li><span>${t("pgDay", day)}</span>
      <b>${new Date(`${iso}T12:00:00`).toLocaleDateString(locale(), { weekday: "long", day: "numeric", month: "long", year: "numeric" })}</b></li>`).join("")}</ul>
      <p class="muted pg-small">${t("pgHajjNote")}</p>`;
  } catch (_) { box.innerHTML = ""; }
}

function body() {
  const L = lang();
  if (tab === "umrah") return steps(UMRAH[L]);
  if (tab === "hajj") return `<div class="pg-hajj" id="pgHajjDates"></div>${steps(HAJJ[L])}`;
  if (tab === "miqat") return steps(MIQAT[L]);
  if (tab === "check") return `<ul class="pg-check">${CHECK[L].map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`;
  const today = new Date().toISOString().slice(0, 10);
  return `<div class="pg-pick"><select id="pgCitySel" class="ev-country"><option value="makkah">${t("pgCity").makkah}</option>
    <option value="madinah">${t("pgCity").madinah}</option></select>
    <label><span>${t("pgDate")}</span> <input type="date" id="pgDateSel" class="w-in" value="${today}"></label></div><div id="pgPrayers"></div>`;
}

function render() {
  if ($("pilgrimage").hidden) return;
  $("pgTabs").innerHTML = Object.entries(t("pgTabs")).map(([k, v]) => `<button type="button" role="tab" data-tab="${k}" class="${k === tab ? "on" : ""}" aria-selected="${k === tab}">${v}</button>`).join("");
  $("pgBody").innerHTML = body() + `<p class="pg-links"><b>${t("pgLinks")}:</b> <a href="${NUSUK}" target="_blank" rel="noopener">Nusuk</a> ·
    <a href="${MINISTRY}" target="_blank" rel="noopener">${lang() === "ar" ? "وزارة الحج والعمرة" : "Ministry of Hajj and Umrah"}</a></p>`;
  if (!$("pgPlanBox").firstElementChild) $("pgPlanBox").innerHTML = planForm();  // kept across tabs (typed values)
  if (tab === "prayers") {
    prayers();
    $("pgCitySel").addEventListener("change", prayers);
    $("pgDateSel").addEventListener("change", prayers);
  }
  if (tab === "hajj") hajjDates();
}

function submit(e) {
  e.preventDefault();
  const f = new FormData(e.target);
  const from = String(f.get("from") || "").trim(), start = String(f.get("start") || "");
  if (!from || !start) { $("pgErr").hidden = false; $("pgErr").textContent = t("pgFill"); return; }
  const nights = Math.max(2, +f.get("nights") || 7);
  const mk = Math.min(nights, Math.max(1, +f.get("makkah") || nights));
  const date = new Date(`${start}T12:00:00`).toLocaleDateString(locale(), { day: "numeric", month: "long", year: "numeric" });
  closePilgrimage();
  app.send(t("pgMsg", nights, mk, nights - mk, date, Math.max(1, +f.get("pax") || 1), String(f.get("budget") || "").trim(), from));
}

export function openPilgrimage() {
  app.beforeOpen();
  $("pilgrimage").hidden = false;
  document.body.classList.add("dash-open");
  $("pilgrimage").scrollTo({ top: 0 });
  if (location.hash !== "#hajj-umrah") history.pushState(null, "", "#hajj-umrah");
  render();
}
export function closePilgrimage() {
  if ($("pilgrimage").hidden) return;
  $("pilgrimage").hidden = true;
  document.body.classList.remove("dash-open");
  if (location.hash === "#hajj-umrah") history.replaceState(null, "", location.pathname + location.search);
}
export function refreshPilgrimageLanguage() {
  if ($("pgPlanBox")) $("pgPlanBox").innerHTML = "";  // redrawn in the new language
  render();
}

export function initPilgrimage(hooks) {
  app = hooks;
  document.querySelectorAll("[data-pilgrimage]").forEach((b) => b.addEventListener("click", openPilgrimage));
  $("pgBack").addEventListener("click", closePilgrimage);
  $("pgTabs").addEventListener("click", (e) => {
    const b = e.target.closest("[data-tab]");
    if (b) { tab = b.dataset.tab; render(); }
  });
  $("pgPlanBox").addEventListener("submit", submit);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closePilgrimage(); });
  window.addEventListener("popstate", () => { if (location.hash === "#hajj-umrah") openPilgrimage(); else closePilgrimage(); });
  if (location.hash === "#hajj-umrah") openPilgrimage();
}
