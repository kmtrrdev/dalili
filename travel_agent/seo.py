"""Search-engine pages: everything Google can read without running the chat app.

- The home page (`/` English, `/ar` Arabic) gets full meta tags, Open Graph / Twitter cards, hreflang alternates and
  JSON-LD (WebApplication + Organization), injected into the app's index.html.
- Destination guides (`/guides/<slug>`, `/ar/guides/<slug>`): server-rendered, original content written by the model
  from each destination's Wikivoyage guide (scripts/build_guides.py -> seo/guides/<slug>.json), with
  TouristDestination, FAQPage and BreadcrumbList structured data and a "plan this trip" link into the planner.
- `/robots.txt`, `/sitemap.xml` (every page in both languages, with hreflang), `/privacy`, `/terms`.

Pages are plain HTML with inline CSS: fast, crawlable, no JavaScript needed.
"""

from __future__ import annotations

import json
import os
from datetime import date
from functools import lru_cache
from html import escape
from urllib.parse import quote

from .config import PROJECT_DIR

GUIDES_DIR = PROJECT_DIR / "seo" / "guides"
APP_NAME = "Dalili AI Travel Planner"
APP_NAME_AR = "دليلي - مخطط الرحلات بالذكاء الاصطناعي"
LAST_UPDATED = "2026-10-04"


def public_url(request_base: str = "") -> str:
    """The site's canonical origin: PUBLIC_URL in production, else whatever the request came in on."""
    return (os.getenv("PUBLIC_URL") or request_base or "http://127.0.0.1:8001").rstrip("/")


# ---------------------------------------------------------------------------
# Guide data
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def guides() -> dict[str, dict]:
    """slug -> guide (both languages). Only complete guides are published."""
    out = {}
    if GUIDES_DIR.exists():
        for f in sorted(GUIDES_DIR.glob("*.json")):
            try:
                g = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if g.get("en") and g.get("ar"):
                out[g["slug"]] = g
    return out


# ---------------------------------------------------------------------------
# Shared page shell
# ---------------------------------------------------------------------------

CSS = """
:root{--bg:#070b14;--card:#0f1626;--line:#1e2a40;--text:#e8eefc;--muted:#9fb0cf;--accent:#2dd4bf;--accent2:#38bdf8}
@media (prefers-color-scheme: light){:root{--bg:#f6f8fc;--card:#fff;--line:#dfe6f2;--text:#0d1626;--muted:#55657f;--accent:#0d9488;--accent2:#0284c7}}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--text);font:16px/1.65 Inter,system-ui,-apple-system,"Segoe UI",Roboto,Cairo,sans-serif}
[dir=rtl] body{font-family:Cairo,system-ui,sans-serif}
a{color:var(--accent)}
.wrap{max-width:880px;margin:0 auto;padding:0 18px}
header.top{border-bottom:1px solid var(--line);position:sticky;top:0;background:color-mix(in srgb,var(--bg) 88%,transparent);backdrop-filter:blur(8px);z-index:2}
header.top .wrap{display:flex;align-items:center;gap:14px;height:60px}
.brand{font:700 20px "Space Grotesk",Inter,sans-serif;color:var(--text);text-decoration:none}.brand span{color:var(--accent)}
header nav{margin-inline-start:auto;display:flex;gap:14px;font-size:14px}header nav a{color:var(--muted);text-decoration:none}
.crumbs{font-size:13px;color:var(--muted);margin:22px 0 4px}.crumbs a{color:var(--muted)}
h1{font:700 clamp(28px,5vw,42px)/1.15 "Space Grotesk",Inter,sans-serif;margin:8px 0 14px}
[dir=rtl] h1,[dir=rtl] h2{font-family:Cairo,sans-serif}
h2{font:700 22px/1.3 "Space Grotesk",Inter,sans-serif;margin:34px 0 10px}
.lead{font-size:18px;color:var(--muted)}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:18px 20px;margin:12px 0}
.cta{display:inline-block;background:linear-gradient(90deg,var(--accent),var(--accent2));color:#04121a;font-weight:700;
 padding:13px 22px;border-radius:12px;text-decoration:none;margin:10px 0}
ul{padding-inline-start:20px}li{margin:6px 0}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:10px}
.grid a{display:block;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px;text-decoration:none;color:var(--text)}
.grid small{color:var(--muted)}
details{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 16px;margin:8px 0}
summary{font-weight:600;cursor:pointer}
footer{border-top:1px solid var(--line);margin-top:48px;padding:22px 0 40px;color:var(--muted);font-size:13px}
footer a{color:var(--muted)}
"""

T = {
    "en": {"dir": "ltr", "home": "Home", "guides": "Travel guides", "plan": "Plan a trip", "privacy": "Privacy",
           "terms": "Terms", "best": "Best time to visit", "sights": "Top things to see", "around": "Getting around",
           "food": "What to eat", "budget": "Money-saving tips", "safety": "Safety and etiquette",
           "itin": "A 3-day itinerary", "faq": "Frequently asked questions", "day": "Day",
           "cta": "Plan my {city} trip with real prices", "cta_sub": "Real flights, hotels and opening hours - a checked "
           "day-by-day plan in a minute. Free, and you book only if you want.",
           "source": "Facts based on the {city} guide on Wikivoyage (CC BY-SA 4.0), rewritten by Dalili.",
           "all": "All destinations", "other": "العربية", "prompt": "Plan a trip to {city}",
           "guides_title": "Travel guides for {n} destinations | Dalili AI Travel Planner",
           "guides_desc": "Free travel guides for {n} destinations: best time to visit, top sights, food, budget tips and "
           "3-day itineraries - then plan your trip with real prices.",
           "guides_h1": "Travel guides", "guides_lead": "Pick a destination: the essentials, then a real plan in a minute.",
           "tagline": "Your AI travel planner: real flights, hotels and places, checked day by day."},
    "ar": {"dir": "rtl", "home": "الرئيسية", "guides": "أدلة السفر", "plan": "خطط رحلتك", "privacy": "الخصوصية",
           "terms": "الشروط", "best": "أفضل وقت للزيارة", "sights": "أهم الأماكن السياحية", "around": "التنقل",
           "food": "ماذا تأكل", "budget": "نصائح لتوفير المال", "safety": "الأمان والعادات",
           "itin": "برنامج 3 أيام", "faq": "أسئلة شائعة", "day": "اليوم",
           "cta": "خطط رحلتك إلى {city} بأسعار حقيقية", "cta_sub": "طيران وفنادق ومواعيد فتح حقيقية - خطة يوم بيوم "
           "متراجعة في دقيقة. مجاناً، وأنت تحجز فقط إذا أردت.",
           "source": "المعلومات مبنية على دليل {city} في ويكي الرحلات (Wikivoyage, CC BY-SA 4.0) وأعاد دليلي صياغتها.",
           "all": "كل الوجهات", "other": "English", "prompt": "عايز أخطط رحلة إلى {city}",
           "guides_title": "أدلة سفر لـ {n} وجهة | دليلي - مخطط الرحلات بالذكاء الاصطناعي",
           "guides_desc": "أدلة سفر مجانية لـ {n} وجهة: أفضل وقت للزيارة، أهم الأماكن، الأكل، نصائح التوفير وبرامج 3 أيام - "
           "ثم خطط رحلتك بأسعار حقيقية.",
           "guides_h1": "أدلة السفر", "guides_lead": "اختر وجهتك: أهم المعلومات، ثم خطة حقيقية في دقيقة.",
           "tagline": "مخطط رحلاتك بالذكاء الاصطناعي: طيران وفنادق وأماكن حقيقية، متراجعة يوم بيوم."},
}


def _ld(obj: dict) -> str:
    return '<script type="application/ld+json">' + json.dumps(obj, ensure_ascii=False).replace("</", "<\\/") + "</script>"


def _shell(lang: str, base: str, path_en: str, path_ar: str, title: str, desc: str, body: str,
           ld: list[dict] | None = None, og_type: str = "website") -> str:
    t = T[lang]
    url = base + (path_ar if lang == "ar" else path_en)
    other = base + (path_en if lang == "ar" else path_ar)
    home = "/ar" if lang == "ar" else "/"
    gl = "/ar/guides" if lang == "ar" else "/guides"
    return f"""<!doctype html>
<html lang="{lang}" dir="{t['dir']}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
<meta name="description" content="{escape(desc)}">
<link rel="canonical" href="{escape(url)}">
<link rel="alternate" hreflang="en" href="{escape(base + path_en)}">
<link rel="alternate" hreflang="ar" href="{escape(base + path_ar)}">
<link rel="alternate" hreflang="x-default" href="{escape(base + path_en)}">
<meta name="robots" content="index, follow, max-image-preview:large">
<meta property="og:type" content="{og_type}">
<meta property="og:site_name" content="{escape(APP_NAME)}">
<meta property="og:title" content="{escape(title)}">
<meta property="og:description" content="{escape(desc)}">
<meta property="og:url" content="{escape(url)}">
<meta property="og:image" content="{escape(base)}/static/og.png">
<meta property="og:locale" content="{'ar_AR' if lang == 'ar' else 'en_US'}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{escape(title)}">
<meta name="twitter:description" content="{escape(desc)}">
<meta name="theme-color" content="#070b14">
<link rel="icon" href="/static/favicon.svg" type="image/svg+xml">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&family=Space+Grotesk:wght@600;700&family=Cairo:wght@400;600;700&display=swap" rel="stylesheet">
<style>{CSS}</style>
{''.join(_ld(x) for x in (ld or []))}
</head>
<body>
<header class="top"><div class="wrap">
<a class="brand" href="{home}">Dal<span>ili</span></a>
<nav><a href="{gl}">{t['guides']}</a><a href="{home}">{t['plan']}</a><a href="{escape(other)}" hreflang="{'en' if lang == 'ar' else 'ar'}">{t['other']}</a></nav>
</div></header>
<main class="wrap">
{body}
</main>
<footer><div class="wrap">
<p>{escape(t['tagline'])}</p>
<p><a href="{home}">{t['home']}</a> · <a href="{gl}">{t['guides']}</a> · <a href="{'/ar' if lang == 'ar' else ''}/privacy">{t['privacy']}</a> · <a href="{'/ar' if lang == 'ar' else ''}/terms">{t['terms']}</a></p>
<p>© {date.today().year} {escape(APP_NAME)}</p>
</div></footer>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Destination guide pages
# ---------------------------------------------------------------------------


def _list(items: list[str]) -> str:
    return "<ul>" + "".join(f"<li>{escape(str(x))}</li>" for x in items if x) + "</ul>" if items else ""


def guide_page(slug: str, lang: str, base: str) -> str | None:
    g = guides().get(slug)
    if g is None:
        return None
    c, t = g[lang], T[lang]
    city = c.get("city_name") or g["name"]
    p_en, p_ar = f"/guides/{slug}", f"/ar/guides/{slug}"
    plan_link = ("/ar" if lang == "ar" else "/") + "?q=" + quote(t["prompt"].format(city=city))
    sights = c.get("top_sights") or []
    body = [
        f'<nav class="crumbs"><a href="{"/ar" if lang == "ar" else "/"}">{t["home"]}</a> › '
        f'<a href="{"/ar/guides" if lang == "ar" else "/guides"}">{t["guides"]}</a> › {escape(city)}</nav>',
        f"<h1>{escape(c['h1'])}</h1>",
        "".join(f'<p class="lead">{escape(p)}</p>' if i == 0 else f"<p>{escape(p)}</p>" for i, p in enumerate(c.get("intro") or [])),
        f'<div class="card"><a class="cta" href="{escape(plan_link)}">{escape(t["cta"].format(city=city))}</a>'
        f'<div>{escape(t["cta_sub"])}</div></div>',
    ]
    if c.get("best_time"):
        body.append(f"<h2>{t['best']}</h2><p>{escape(c['best_time'])}</p>")
    if sights:
        body.append(f"<h2>{t['sights']}</h2>" + "".join(
            f'<div class="card"><strong>{escape(s.get("name", ""))}</strong><div>{escape(s.get("why", ""))}</div></div>'
            for s in sights))
    if c.get("getting_around"):
        body.append(f"<h2>{t['around']}</h2><p>{escape(c['getting_around'])}</p>")
    if c.get("food"):
        body.append(f"<h2>{t['food']}</h2>" + _list([f"{f.get('name', '')}: {f.get('note', '')}" for f in c["food"]]))
    if c.get("budget_tips"):
        body.append(f"<h2>{t['budget']}</h2>" + _list(c["budget_tips"]))
    if c.get("safety"):
        body.append(f"<h2>{t['safety']}</h2>" + _list(c["safety"]))
    if c.get("itinerary"):
        body.append(f"<h2>{t['itin']}</h2>" + "".join(
            f'<div class="card"><strong>{t["day"]} {i + 1}</strong><div>{escape(d)}</div></div>'
            for i, d in enumerate(c["itinerary"][:3])))
    if c.get("faq"):
        body.append(f"<h2>{t['faq']}</h2>" + "".join(
            f"<details><summary>{escape(q.get('q', ''))}</summary><p>{escape(q.get('a', ''))}</p></details>" for q in c["faq"]))
    body.append(f'<div class="card"><a class="cta" href="{escape(plan_link)}">{escape(t["cta"].format(city=city))}</a></div>')
    related = [x for x in guides().values() if x["slug"] != slug and x.get("country") == g.get("country")][:6]
    if len(related) < 6:
        related += [x for x in guides().values() if x["slug"] != slug and x not in related
                    and set(x.get("tags", [])) & set(g.get("tags", []))][: 6 - len(related)]
    if related:
        body.append(f"<h2>{t['all']}</h2><div class='grid'>" + "".join(
            f'<a href="{"/ar" if lang == "ar" else ""}/guides/{x["slug"]}">{escape(x[lang].get("city_name") or x["name"])}'
            f'<br><small>{escape(x[lang].get("country_name") or x.get("country", ""))}</small></a>' for x in related) + "</div>")
    body.append(f'<p style="color:var(--muted);font-size:13px;margin-top:28px">{escape(t["source"].format(city=city))} '
                f'<a href="{escape(g.get("source_url", ""))}" rel="nofollow noopener">Wikivoyage</a></p>')

    url = base + (p_ar if lang == "ar" else p_en)
    ld = [
        {"@context": "https://schema.org", "@type": "TouristDestination", "name": city, "url": url,
         "description": c["meta_description"], "inLanguage": lang,
         "containedInPlace": {"@type": "Country", "name": c.get("country_name") or g.get("country")},
         "includesAttraction": [{"@type": "TouristAttraction", "name": s.get("name"), "description": s.get("why")}
                                for s in sights[:10]]},
        {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": t["home"], "item": base + ("/ar" if lang == "ar" else "/")},
            {"@type": "ListItem", "position": 2, "name": t["guides"], "item": base + ("/ar/guides" if lang == "ar" else "/guides")},
            {"@type": "ListItem", "position": 3, "name": city, "item": url}]},
    ]
    if c.get("faq"):
        ld.append({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
            {"@type": "Question", "name": q.get("q"), "acceptedAnswer": {"@type": "Answer", "text": q.get("a")}}
            for q in c["faq"]]})
    return _shell(lang, base, p_en, p_ar, c["title"], c["meta_description"], "\n".join(body), ld, og_type="article")


def guides_index(lang: str, base: str) -> str:
    t = T[lang]
    items = sorted(guides().values(), key=lambda g: (g[lang].get("country_name") or g.get("country", ""), g["name"]))
    n = len(items)
    cards = "".join(
        f'<a href="{"/ar" if lang == "ar" else ""}/guides/{g["slug"]}">{escape(g[lang].get("city_name") or g["name"])}'
        f'<br><small>{escape(g[lang].get("country_name") or g.get("country", ""))}</small></a>' for g in items)
    body = (f'<nav class="crumbs"><a href="{"/ar" if lang == "ar" else "/"}">{t["home"]}</a> › {t["guides"]}</nav>'
            f'<h1>{t["guides_h1"]}</h1><p class="lead">{t["guides_lead"]}</p><div class="grid">{cards}</div>')
    ld = [{"@context": "https://schema.org", "@type": "ItemList", "itemListElement": [
        {"@type": "ListItem", "position": i + 1, "url": base + ("/ar" if lang == "ar" else "") + f"/guides/{g['slug']}",
         "name": g[lang].get("city_name") or g["name"]} for i, g in enumerate(items)]}]
    return _shell(lang, base, "/guides", "/ar/guides", t["guides_title"].format(n=n), t["guides_desc"].format(n=n), body, ld)


# ---------------------------------------------------------------------------
# Home page head (injected into the app's index.html)
# ---------------------------------------------------------------------------

HOME = {
    "en": {"title": "Dalili - AI Travel Planner | Real flights, hotels & day-by-day itineraries",
           "desc": "Plan a whole trip in a minute with AI: real flights and hotels, top sights, food and weather in a "
                   "checked day-by-day itinerary. Free."},
    "ar": {"title": "دليلي - مخطط رحلات بالذكاء الاصطناعي | طيران وفنادق وبرنامج يوم بيوم",
           "desc": "خطط رحلتك كاملة في دقيقة بالذكاء الاصطناعي: طيران وفنادق حقيقية، أهم الأماكن، الأكل والطقس، وبرنامج "
                   "يوم بيوم في حدود ميزانيتك. مجاناً."},
}


@lru_cache(maxsize=4)
def _index_html() -> str:
    return (PROJECT_DIR / "frontend" / "index.html").read_text(encoding="utf-8")


def index_page(lang: str, base: str) -> str:
    h = HOME[lang]
    url = base + ("/ar" if lang == "ar" else "/")
    head = f"""<title>{escape(h['title'])}</title>
  <meta name="description" content="{escape(h['desc'])}">
  <link rel="canonical" href="{escape(url)}">
  <link rel="alternate" hreflang="en" href="{escape(base)}/">
  <link rel="alternate" hreflang="ar" href="{escape(base)}/ar">
  <link rel="alternate" hreflang="x-default" href="{escape(base)}/">
  <meta name="robots" content="index, follow, max-image-preview:large">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="{escape(APP_NAME)}">
  <meta property="og:title" content="{escape(h['title'])}">
  <meta property="og:description" content="{escape(h['desc'])}">
  <meta property="og:url" content="{escape(url)}">
  <meta property="og:image" content="{escape(base)}/static/og.png">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="theme-color" content="#070b14">
  <link rel="manifest" href="/static/manifest.webmanifest">
  <link rel="apple-touch-icon" href="/static/apple-touch-icon.png">
  {_ld({"@context": "https://schema.org", "@type": "WebApplication", "name": APP_NAME if lang == "en" else APP_NAME_AR,
        "url": url, "applicationCategory": "TravelApplication", "operatingSystem": "Web, iOS, Android",
        "inLanguage": ["en", "ar"], "description": h["desc"],
        "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"}})}
  {_ld({"@context": "https://schema.org", "@type": "Organization", "name": "Dalili", "url": base + "/",
        "logo": base + "/static/icon-512.png"})}"""
    html = _index_html()
    start, end = html.find("<title>"), html.find("</title>") + len("</title>")
    desc_end = html.find(">", html.find('<meta name="description"', end)) + 1
    html = html[:start] + head + html[desc_end:]
    if lang == "ar":
        html = html.replace('<html lang="en">', '<html lang="ar" dir="rtl">', 1)
    # A crawlable link to the guides from the home page (internal linking), shown in the top bar.
    gl = "/ar/guides" if lang == "ar" else "/guides"
    label = "أدلة السفر" if lang == "ar" else "Travel guides"
    return html.replace('<div class="status" id="status"',
                        f'<a class="btn ghost guides-link" href="{gl}">{label}</a>\n    <div class="status" id="status"', 1)


# ---------------------------------------------------------------------------
# robots.txt, sitemap.xml
# ---------------------------------------------------------------------------


def robots(base: str) -> str:
    return (f"User-agent: *\nAllow: /\nDisallow: /api/\nDisallow: /static/vendor/\n\nSitemap: {base}/sitemap.xml\n")


def sitemap(base: str) -> str:
    def entry(en: str, ar: str, prio: str) -> str:
        alts = (f'<xhtml:link rel="alternate" hreflang="en" href="{escape(base + en)}"/>'
                f'<xhtml:link rel="alternate" hreflang="ar" href="{escape(base + ar)}"/>'
                f'<xhtml:link rel="alternate" hreflang="x-default" href="{escape(base + en)}"/>')
        return "".join(f"<url><loc>{escape(base + p)}</loc><lastmod>{LAST_UPDATED}</lastmod>"
                       f"<priority>{prio}</priority>{alts}</url>" for p in (en, ar))

    urls = [entry("/", "/ar", "1.0"), entry("/guides", "/ar/guides", "0.9")]
    urls += [entry(f"/guides/{s}", f"/ar/guides/{s}", "0.8") for s in guides()]
    urls += [entry("/privacy", "/ar/privacy", "0.3"), entry("/terms", "/ar/terms", "0.3")]
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
            'xmlns:xhtml="http://www.w3.org/1999/xhtml">' + "".join(urls) + "</urlset>")


# ---------------------------------------------------------------------------
# Privacy policy and terms (required by the App Store and Google Play)
# ---------------------------------------------------------------------------

LEGAL = {
    "privacy": {
        "en": ("Privacy policy", [
            ("What Dalili is", "Dalili is an AI travel planner. It researches and plans trips; it never books or takes "
             "payments. Bookings happen on the airline, hotel or other provider's own site."),
            ("What we collect", "The messages you send to plan a trip, the trips we plan for you, and the preferences you "
             "tell us or that we learn from your feedback (for example pace, food or walking). If you create an account: "
             "your name, email address and a securely hashed password. Guests get a random identifier instead."),
            ("How we use it", "Only to plan and improve your trips and the suggestions shown to you. Your messages are sent "
             "to our AI model provider (Microsoft Azure AI) and searches to travel data providers (such as Google results "
             "via SerpApi, OpenRouteService, Geoapify, Open-Meteo and Wikivoyage) to get real prices, places and weather. "
             "We do not sell your data and we do not use it for advertising."),
            ("Cookies", "One cookie keeps you signed in and one remembers your guest trips. No advertising or tracking "
             "cookies."),
            ("Keeping and deleting", "Your trips are kept until you delete them or your account. You can delete your account "
             "and all its trips at any time in the app (Profile -> Delete account) or on the website."),
            ("Security", "Connections are encrypted (HTTPS). Passwords are hashed with scrypt; session tokens are stored "
             "only as hashes."),
            ("Children", "Dalili is not directed at children under 13."),
            ("Contact", "Questions or requests about your data: {contact}."),
        ]),
        "ar": ("سياسة الخصوصية", [
            ("ما هو دليلي", "دليلي مخطط رحلات بالذكاء الاصطناعي. يبحث ويخطط الرحلات، ولا يحجز أبداً ولا يأخذ أي مدفوعات. "
             "الحجز يتم على موقع شركة الطيران أو الفندق أو مقدم الخدمة نفسه."),
            ("ما نجمعه", "الرسائل التي ترسلها لتخطيط الرحلة، والرحلات التي نخططها لك، والتفضيلات التي تخبرنا بها أو نتعلمها من "
             "ملاحظاتك (مثل الإيقاع أو الأكل أو المشي). عند إنشاء حساب: اسمك وبريدك الإلكتروني وكلمة مرور مشفرة بأمان. "
             "الضيوف يحصلون على معرف عشوائي بدلاً من ذلك."),
            ("كيف نستخدمه", "فقط لتخطيط رحلاتك وتحسينها وتحسين الاقتراحات. تُرسل رسائلك إلى مزود نموذج الذكاء الاصطناعي "
             "(Microsoft Azure AI) وتُرسل عمليات البحث إلى مزودي بيانات السفر (مثل نتائج جوجل عبر SerpApi و OpenRouteService "
             "و Geoapify و Open-Meteo وويكي الرحلات) للحصول على أسعار وأماكن وطقس حقيقية. لا نبيع بياناتك ولا نستخدمها للإعلانات."),
            ("ملفات تعريف الارتباط", "ملف واحد يبقيك مسجلاً للدخول وآخر يتذكر رحلاتك كضيف. لا توجد ملفات إعلانات أو تتبع."),
            ("الحفظ والحذف", "تبقى رحلاتك محفوظة حتى تحذفها أو تحذف حسابك. يمكنك حذف حسابك وكل رحلاته في أي وقت من التطبيق "
             "(الملف الشخصي ← حذف الحساب) أو من الموقع."),
            ("الأمان", "الاتصالات مشفرة (HTTPS). كلمات المرور مشفرة بـ scrypt، ورموز الجلسات تُحفظ كقيم مشفرة فقط."),
            ("الأطفال", "دليلي غير موجه للأطفال دون 13 عاماً."),
            ("التواصل", "للأسئلة أو الطلبات المتعلقة ببياناتك: {contact}."),
        ]),
    },
    "terms": {
        "en": ("Terms of use", [
            ("The service", "Dalili plans trips with AI using live data from third parties. It does not book anything; "
             "you make your own bookings with the providers."),
            ("Prices and information", "Prices, schedules and opening hours come from providers at the time of planning and "
             "can change. Some prices are estimates and are labelled as such. Always confirm with the provider before you "
             "book or travel."),
            ("Your responsibility", "You are responsible for your bookings, travel documents, visas, insurance and safety "
             "decisions. Dalili's suggestions are not professional legal, medical or visa advice."),
            ("Fair use", "Don't misuse the service, attempt to break it or use it to send unlawful content. We may limit "
             "or suspend use that harms the service or other users."),
            ("Liability", "The service is provided as is. To the extent the law allows, Dalili is not liable for losses "
             "arising from bookings, price changes or inaccurate third-party information."),
            ("Changes", "We may update these terms; the date below shows the latest version."),
        ]),
        "ar": ("شروط الاستخدام", [
            ("الخدمة", "دليلي يخطط الرحلات بالذكاء الاصطناعي باستخدام بيانات مباشرة من جهات خارجية. لا يحجز أي شيء؛ "
             "أنت تحجز بنفسك مع مقدمي الخدمة."),
            ("الأسعار والمعلومات", "الأسعار والمواعيد ومواعيد الفتح مأخوذة من مقدمي الخدمة وقت التخطيط وقد تتغير. بعض الأسعار "
             "تقديرية ومعلّمة بذلك. تأكد دائماً من مقدم الخدمة قبل الحجز أو السفر."),
            ("مسؤوليتك", "أنت مسؤول عن حجوزاتك ووثائق السفر والتأشيرات والتأمين وقرارات السلامة. اقتراحات دليلي ليست استشارة "
             "قانونية أو طبية أو استشارة تأشيرات."),
            ("الاستخدام العادل", "لا تسئ استخدام الخدمة أو تحاول تعطيلها أو استخدامها لمحتوى غير قانوني. قد نقيد الاستخدام "
             "الذي يضر بالخدمة أو بالمستخدمين."),
            ("المسؤولية", "تُقدم الخدمة كما هي. في حدود ما يسمح به القانون، دليلي غير مسؤول عن الخسائر الناتجة عن الحجوزات "
             "أو تغير الأسعار أو معلومات الجهات الخارجية غير الدقيقة."),
            ("التغييرات", "قد نحدّث هذه الشروط؛ التاريخ أدناه يوضح آخر نسخة."),
        ]),
    },
}


def legal_page(kind: str, lang: str, base: str) -> str:
    title, sections = LEGAL[kind][lang]
    updated = "آخر تحديث" if lang == "ar" else "Last updated"
    contact = os.getenv("CONTACT_EMAIL", "the contact address in the app store listing")
    body = f"<h1>{escape(title)}</h1><p class='lead'>{updated}: {LAST_UPDATED}</p>" + "".join(
        f"<h2>{escape(h)}</h2><p>{escape(p.format(contact=contact))}</p>" for h, p in sections)
    return _shell(lang, base, f"/{kind}", f"/ar/{kind}", f"{title} | {APP_NAME}", sections[0][1][:155], body)
