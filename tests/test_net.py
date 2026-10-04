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


def test_unsupported_engine_is_remembered(isolated, monkeypatch):
    monkeypatch.setattr(settings, "http_mode", "cache")
    net.start_turn()
    for _ in range(2):
        with pytest.raises(net.ProviderError):
            anyio.run(lambda: net.fetch_json("serpapi", "https://x.test/unsupported", {}, ttl_s=100))
    assert len(isolated) == 1, "second attempt answered from cache without spending a search"
