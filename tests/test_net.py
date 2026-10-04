"""HTTP layer: key stripping, record/replay, quota guard, stale fallback."""

import anyio
import httpx
import pytest

from travel_agent import net
from travel_agent.config import settings


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(net, "_cache", net._Cache(str(tmp_path / "c.sqlite")))
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if "unsupported" in str(request.url):
            return httpx.Response(400, json={"error": "Unsupported `x` search engine."})
        return httpx.Response(200, json={"ok": True, "n": len(calls)})

    monkeypatch.setattr(net, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(settings, "serpapi_key", "secret-key")
    return calls


def test_recorded_fixtures_contain_no_key_parameters():
    import json
    import sqlite3
    from pathlib import Path

    db = sqlite3.connect(Path(__file__).parent / "fixtures" / "http_cache.sqlite")
    for (params,) in db.execute("SELECT params FROM http_cache"):
        assert not (set(json.loads(params)) & net.SECRET_PARAMS)


def test_errors_never_contain_api_keys(monkeypatch):
    monkeypatch.setattr(settings, "serpapi_key", "TOPSECRET")
    assert "TOPSECRET" not in str(net.ProviderError("failed: https://serpapi.com/search.json?api_key=TOPSECRET"))


def test_api_keys_never_part_of_cache_key():
    assert net.cache_key("GET", "u", {"q": "rome", "api_key": "A"}) == net.cache_key("GET", "u", {"q": "rome", "api_key": "B"})


def test_cache_mode_calls_once_then_serves_cache(isolated, monkeypatch):
    monkeypatch.setattr(settings, "http_mode", "cache")
    a = anyio.run(lambda: net.fetch_json("svc", "https://x.test/a", {"q": 1, "apiKey": "k"}, ttl_s=100))
    b = anyio.run(lambda: net.fetch_json("svc", "https://x.test/a", {"q": 1, "apiKey": "k"}, ttl_s=100))
    assert a == b and len(isolated) == 1


def test_replay_never_touches_network(isolated, monkeypatch):
    monkeypatch.setattr(settings, "http_mode", "replay")
    with pytest.raises(net.ReplayMiss):
        anyio.run(lambda: net.fetch_json("svc", "https://x.test/missing", {}, ttl_s=1))
    assert not isolated


def test_serpapi_per_turn_cap(isolated, monkeypatch):
    monkeypatch.setattr(settings, "http_mode", "live")
    monkeypatch.setattr(settings, "serpapi_calls_per_turn", 2)
    net.start_turn()
    anyio.run(lambda: net.serpapi("google_maps", 10, q="a"))
    anyio.run(lambda: net.serpapi("google_maps", 10, q="b"))
    with pytest.raises(net.QuotaExceeded):
        anyio.run(lambda: net.serpapi("google_maps", 10, q="c"))
    net.start_turn()


def test_page_fetch_refuses_internal_targets():
    for url in ("http://localhost/x", "http://127.0.0.1/", "http://169.254.169.254/latest/meta-data",
                "http://2130706433/", "http://0x7f000001/", "http://0177.0.0.1/", "http://10.0.0.5/",
                "http://example.com:6379/", "file:///etc/passwd", "javascript:alert(1)", "http://intranet.local/"):
        assert not net._public_http_url(url), url
    assert net._public_http_url("https://www.example.com/menu")


def test_page_redirect_to_an_internal_address_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(net, "_cache", net._Cache(str(tmp_path / "c.sqlite")))
    monkeypatch.setattr(settings, "http_mode", "live")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data"})

    async def public(url):
        return "169.254" not in url

    monkeypatch.setattr(net, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(net, "_resolves_public", public)
    with pytest.raises(net.ProviderError, match="refused"):
        anyio.run(net.fetch_page, "https://restaurant.example/menu")


def test_cached_data_keeps_its_real_fetch_time(isolated, monkeypatch):
    """A response served from cache must not look freshly retrieved."""
    import time

    from travel_agent.models import Metadata

    monkeypatch.setattr(settings, "http_mode", "cache")
    anyio.run(lambda: net.fetch_json("svc", "https://x.test/t", {}, ttl_s=10_000))
    key = net.cache_key("GET", "https://x.test/t", {})
    with net.cache().lock, net.cache().conn:
        net.cache().conn.execute("UPDATE http_cache SET fetched_at = ? WHERE key = ?", (time.time() - 5 * 86400, key))

    async def parse():
        await net.fetch_json("svc", "https://x.test/t", {}, ttl_s=30 * 86400)
        return Metadata(source="s", provider="p")

    meta = anyio.run(parse)
    assert (time.time() - meta.retrieved_at.timestamp()) > 4 * 86400 and not meta.stale


def test_unsupported_engine_is_remembered(isolated, monkeypatch):
    monkeypatch.setattr(settings, "http_mode", "cache")
    net.start_turn()
    for _ in range(2):
        with pytest.raises(net.ProviderError):
            anyio.run(lambda: net.fetch_json("serpapi", "https://x.test/unsupported", {}, ttl_s=100))
    assert len(isolated) == 1, "second attempt answered from cache without spending a search"
