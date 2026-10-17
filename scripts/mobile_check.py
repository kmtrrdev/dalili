"""Phone-layout check: every screen of the web app at phone size, English and Arabic.

Starts the app locally on recorded real data (offline, no keys, no quota), creates a real trip through the API in
the browser, then opens each screen (home, chat, trip board and every tab, booking and rating dialogs, the form,
the Trip Book) at 390x844 with touch, and reports any element wider than the screen plus a screenshot per screen.

    python scripts/mobile_check.py              # needs: pip install playwright (uses the installed Edge/Chrome)
    python scripts/mobile_check.py --url https://...   # check a deployed site instead (creates a real trip there)
Exit code 1 if any screen overflows horizontally.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".cache" / "mobile_check"
ROME = "7 days in Rome from October 12 for two, budget $3,500. We love food, history and photography."

# Elements wider than the viewport (ignoring ones clipped by an overflow-hidden ancestor or purposely scrolling).
OVERFLOW_JS = """() => {
  const vw = document.documentElement.clientWidth;
  const out = [];
  // Clipped when any ancestor that clips or scrolls horizontally lies within the screen (a map's oversized SVG
  // inside its container, a scrolling tab strip).
  const clipped = (el) => { for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
    const s = getComputedStyle(p), r = p.getBoundingClientRect();
    if (/(hidden|auto|scroll|clip)/.test(s.overflowX) && r.right <= vw + 1 && r.left >= -1) return true; }
    return false; };
  for (const el of document.querySelectorAll('body *')) {
    const r = el.getBoundingClientRect();
    if (!r.width || getComputedStyle(el).position === 'fixed' && r.right <= vw + 1) continue;
    if ((r.right > vw + 1 || r.left < -1) && !clipped(el)) {
      const id = el.id ? '#' + el.id : '', cls = el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\\s+/).slice(0, 2).join('.') : '';
      out.push({ el: el.tagName.toLowerCase() + id + cls, left: Math.round(r.left), right: Math.round(r.right), width: Math.round(r.width) });
    }
  }
  // keep only outermost offenders
  return { page: document.documentElement.scrollWidth, vw, offenders: out.slice(0, 12) };
}"""


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_local() -> tuple[subprocess.Popen, str]:
    port = free_port()
    env = {**os.environ, "TRAVEL_AGENT_HTTP_MODE": "replay", "TRAVEL_AGENT_LLM": "0", "TRAVEL_AGENT_RULES_FALLBACK": "1",
           "TRAVEL_AGENT_HTTP_CACHE": str(ROOT / "tests" / "fixtures" / "http_cache.sqlite"),
           "TRAVEL_AGENT_TODAY": "2026-09-27", "TRAVEL_AGENT_DB": str(OUT / "check.db"), "DATABASE_URL": ""}
    for k in ("SERPAPI_API_KEY", "ORS_API_KEY", "OPENTRIPMAP_API_KEY", "GEOAPIFY_API_KEY"):
        env.setdefault(k, "replay-placeholder")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "check.db").unlink(missing_ok=True)
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "travel_agent.api:app", "--port", str(port)],
                            cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}"
    for _ in range(60):
        try:
            import urllib.request
            urllib.request.urlopen(url + "/api/health", timeout=1)
            return proc, url
        except Exception:
            time.sleep(0.5)
    proc.kill()
    raise SystemExit("local server did not start")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url")
    ap.add_argument("--width", type=int, default=390)
    args = ap.parse_args()
    from playwright.sync_api import sync_playwright

    proc, url = (None, args.url.rstrip("/")) if args.url else start_local()
    results = {}
    try:
        with sync_playwright() as pw:
            browser = None
            for channel in ("msedge", "chrome", None):
                try:
                    browser = pw.chromium.launch(channel=channel) if channel else pw.chromium.launch()
                    break
                except Exception:
                    continue
            if browser is None:
                raise SystemExit("no Chromium-based browser found")
            for lang in ("en", "ar"):
                ctx = browser.new_context(viewport={"width": args.width, "height": 844}, device_scale_factor=2,
                                          is_mobile=True, has_touch=True, locale="ar-EG" if lang == "ar" else "en-US")
                page = ctx.new_page()

                def shot(name: str) -> None:
                    page.wait_for_timeout(700)
                    res = page.evaluate(OVERFLOW_JS)
                    results[f"{lang}:{name}"] = res
                    page.screenshot(path=str(OUT / f"{lang}_{name}.png"), full_page=False)

                page.goto(url + ("/ar" if lang == "ar" else "/"), wait_until="networkidle")
                shot("home")
                trip_id = page.evaluate("""async (msg) => { const r = await fetch('/api/chat', {method: 'POST',
                    headers: {'Content-Type': 'application/json'}, body: JSON.stringify({message: msg})});
                    return (await r.json()).trip_id; }""", ROME)
                page.evaluate("(id) => localStorage.setItem('tripId', id)", trip_id)
                page.reload(wait_until="networkidle")
                page.wait_for_selector("body.has-trip #tabs", state="visible", timeout=20000)
                page.wait_for_timeout(1200)
                shot("board")
                for tab in page.query_selector_all("#tabs [role=tab]"):
                    if not tab.is_visible():
                        continue  # tabs that only exist for some trips (e.g. multi-city)
                    name = tab.get_attribute("data-tab")
                    tab.click()
                    shot(f"tab-{name}")
                for btn, name in (("#bookTrip", "booking"), ("#ratePlan", "rating")):
                    el = page.query_selector(btn)
                    if el and el.is_visible():
                        el.click()
                        shot(name)
                        page.keyboard.press("Escape")
                page.goto(f"{url}/api/trips/{trip_id}/book", wait_until="networkidle")
                shot("tripbook")
                ctx.close()
            browser.close()
    finally:
        if proc:
            proc.terminate()
    bad = {k: v for k, v in results.items() if v["page"] > v["vw"] + 1 or v["offenders"]}
    for k, v in results.items():
        flag = "OVERFLOW" if k in bad else "ok"
        print(f"{flag:8} {k:24} page={v['page']} vw={v['vw']}" + ("" if k not in bad else
              "  " + json.dumps(v["offenders"][:5])))
    print(f"screenshots: {OUT}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
