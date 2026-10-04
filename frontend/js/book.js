// Trip Book interactions: globe cover, scroll-spy contents, progress, reveals, lazy day maps, checklists.
import { Globe } from "./globe.js";

const data = JSON.parse(document.getElementById("book-data").textContent);
const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

// ---------------------------------------------------------------- globe cover
let globe = null;
try {
  globe = new Globe(document.getElementById("globe"), document.getElementById("globeLabels"));
  const offset = () => {
    const wide = window.innerWidth > 900;
    globe.setCenterOffset(wide ? window.innerWidth * 0.22 : 0);
    const cx = window.innerWidth / 2 + (wide ? window.innerWidth * 0.22 : 0);
    const half = wide ? window.innerWidth * 0.26 : window.innerWidth / 2 - 16;
    globe.setSafeArea(cx - half, cx + half);
  };
  offset();
  window.addEventListener("resize", offset);
  globe.setJourney(data.origin, data.stops || [data.dest]);
  globe.setTheme(document.documentElement.dataset.theme === "light" ? "light" : "dark");
} catch (err) {
  document.getElementById("globe").remove(); // no WebGL: the book still works without the globe
}

// ---------------------------------------------------------------- light / dark (shared with the planner)
document.getElementById("themeToggle")?.addEventListener("click", () => {
  const next = document.documentElement.dataset.theme === "light" ? "dark" : "light";
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem("theme", next); } catch (_) { /* storage unavailable */ }
  globe?.setTheme(next);
});

// ---------------------------------------------------------------- scroll: globe fade + progress
const cover = document.querySelector(".cover");
function onScroll() {
  const k = Math.min(1, window.scrollY / Math.max(cover.offsetHeight, 1));
  document.body.style.setProperty("--globe", String(1 - k * 0.82));
  const max = document.documentElement.scrollHeight - window.innerHeight;
  document.getElementById("progress").style.width = `${Math.min(100, (window.scrollY / Math.max(max, 1)) * 100)}%`;
}
window.addEventListener("scroll", onScroll, { passive: true });
onScroll();

// ---------------------------------------------------------------- scroll-spy contents
const links = new Map([...document.querySelectorAll(".toc a")].map((a) => [a.dataset.target, a]));
const spy = new IntersectionObserver((entries) => {
  for (const en of entries) {
    if (!en.isIntersecting) continue;
    links.forEach((a) => a.classList.remove("active"));
    const a = links.get(en.target.id);
    if (a) { a.classList.add("active"); a.scrollIntoView({ block: "nearest" }); }
  }
}, { rootMargin: "-35% 0px -60% 0px" });
document.querySelectorAll(".sec").forEach((s) => spy.observe(s));

// ---------------------------------------------------------------- reveals + charts
const reveal = new IntersectionObserver((entries) => {
  for (const en of entries) {
    if (!en.isIntersecting) continue;
    en.target.classList.add("in");
    en.target.querySelectorAll(".donut circle[data-dash]").forEach((c) => c.setAttribute("stroke-dasharray", c.dataset.dash));
    reveal.unobserve(en.target);
  }
}, { threshold: 0, rootMargin: "0px 0px -12% 0px" });  // a ratio threshold never fires for sections taller than the screen
document.querySelectorAll(".reveal, .sec").forEach((el) => (reduceMotion ? el.classList.add("in") : reveal.observe(el)));
if (reduceMotion) document.querySelectorAll(".donut circle[data-dash]").forEach((c) => c.setAttribute("stroke-dasharray", c.dataset.dash));
requestAnimationFrame(() => document.querySelectorAll(".ring .fg").forEach((c) => { c.style.strokeDashoffset = c.dataset.target; }));

// ---------------------------------------------------------------- day maps (lazy)
function buildMap(el) {
  if (!window.L) { el.remove(); return; }
  const day = data.days.find((d) => d.day === +el.dataset.day);
  const map = L.map(el, { scrollWheelZoom: false, zoomControl: true });
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "© OpenStreetMap contributors", maxZoom: 19, className: "dark-tiles",
  }).addTo(map);
  const pts = [];
  const pin = (html) => L.divIcon({ className: "", html, iconSize: [26, 26], iconAnchor: [13, 26] });
  const hotel = (day && day.hotel) || data.hotel;
  if (hotel) {
    const h = [hotel.lat, hotel.lon];
    L.marker(h, { icon: pin('<div class="pin hotel"><b>H</b></div>') }).addTo(map).bindTooltip(hotel.name);
    pts.push(h);
  }
  for (const p of (day ? day.points : [])) {
    const ll = [p.lat, p.lon];
    pts.push(ll);
    L.marker(ll, { icon: pin(`<div class="pin ${p.kind}"><b>${p.n}</b></div>`) }).addTo(map).bindTooltip(p.title);
  }
  if (pts.length > 1) {
    L.polyline(pts, { color: "#0b1220", weight: 7, opacity: 0.7 }).addTo(map);
    L.polyline(pts, { color: "#3de0d0", weight: 4, className: "route-line" }).addTo(map);
  }
  if (pts.length) map.fitBounds(pts, { padding: [30, 30], maxZoom: 15 });
  else if ((day && day.center) || data.center) {
    const c = (day && day.center) || data.center;
    map.setView([c.lat, c.lon], 12);
  }
  setTimeout(() => map.invalidateSize(), 80);
}
const mapObs = new IntersectionObserver((entries) => {
  for (const en of entries) {
    if (en.isIntersecting) { buildMap(en.target); mapObs.unobserve(en.target); }
  }
}, { rootMargin: "300px" });
document.querySelectorAll(".daymap").forEach((m) => mapObs.observe(m));

// ---------------------------------------------------------------- checklists (remembered per trip)
const KEY = `tripbook:${data.trip_id}:checks`;
let saved = {};
try { saved = JSON.parse(localStorage.getItem(KEY) || "{}"); } catch (_) { saved = {}; }
document.querySelectorAll(".check input").forEach((box) => {
  box.checked = !!saved[box.dataset.key];
  box.addEventListener("change", () => {
    saved[box.dataset.key] = box.checked;
    try { localStorage.setItem(KEY, JSON.stringify(saved)); } catch (_) { /* storage unavailable */ }
  });
});
