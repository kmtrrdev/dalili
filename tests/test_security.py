"""Security regression tests: link schemes, CSP, rate limits, forged client IPs, operator-only endpoints, size caps."""

from fastapi.testclient import TestClient

from travel_agent import security
from travel_agent.api import app
from travel_agent.models import Place

client = TestClient(app)


def test_links_from_third_party_data_are_http_only():
    base = dict(id="p", name="x", kind="restaurant", location={"lat": 0, "lon": 0}, cost_per_person={"amount": 10},
                metadata={"source": "s", "provider": "p"})
    for bad in ("javascript:alert(1)", "data:text/html,<script>", " JAVASCRIPT:alert(1)", "file:///etc/passwd"):
        p = Place(**base, website=bad, booking_url=bad, menu_url=bad)
        assert p.website is None and p.booking_url is None and p.menu_url is None
    assert Place(**base, website="https://ok.example").website == "https://ok.example"


def test_pages_carry_a_strict_content_security_policy():
    r = client.get("/")
    csp = r.headers["content-security-policy"]
    assert "script-src 'self'" in csp and "'unsafe-inline'" not in csp.split("script-src")[1].split(";")[0]
    assert "object-src 'none'" in csp and "frame-ancestors 'none'" in csp
    # the page's own inline scripts are allowed by hash, so the site still works
    assert "'sha256-" in csp


def test_expensive_endpoints_are_rate_limited(monkeypatch):
    monkeypatch.setattr(security, "TURNS_PER_IDENTITY", security.RateLimiter(2, 600))
    for _ in range(2):
        assert client.post("/api/parse", json={"text": "Rome in May"}).status_code != 429
    r = client.post("/api/parse", json={"text": "Rome in May"})
    assert r.status_code == 429 and "Retry-After" in r.headers


def test_a_forged_forwarded_for_does_not_change_the_client_ip():
    class Req:
        headers = {"x-forwarded-for": "1.2.3.4, 203.0.113.9"}  # client-supplied first, proxy-appended last
        client = None

    assert security.client_ip(Req()) == "203.0.113.9"


def test_operator_endpoints_are_hidden():
    assert client.get("/api/quota").status_code == 404
    assert client.get("/api/mcp/tools").status_code == 404


def test_oversized_messages_are_rejected():
    r = client.post("/api/chat", json={"message": "x" * (security.MAX_MESSAGE_CHARS + 1)})
    assert r.status_code == 422
