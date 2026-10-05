"""Official-website prices and the full price cascade (scripted model, no network)."""

import anyio

from travel_agent import llm, net, pricing
from travel_agent.models import GeoPoint, Metadata, Money, Place, ResearchBundle, TripContract, Budget
from travel_agent.providers import ai_fallback, official_prices as op

HOME = """<html><body><nav><a href="/pt/sobre/">Sobre</a> <a href="/como-visitar/escolher-o-bilhete/">Bilhetes e preços</a>
<a href="https://blueticket.meo.pt/">Comprar</a> <a href="/menu.pdf">Menu</a></nav><script>var x = "€99";</script>
<p>Bem-vindo ao Castelo</p></body></html>"""
PRICES = """<h1>Escolher o bilhete</h1><p>Bilhete Adulto — 17€</p><p>Jovens 13-25 anos — 8,50€</p>
<p>Seniores &gt; 65 anos — 14€</p><p>Crianças até 12 anos — Gratuito</p>"""


def test_price_links_stay_on_the_official_site():
    links = op.price_links(HOME, "https://castelodesaojorge.pt/", "attraction")
    assert links == ["https://castelodesaojorge.pt/como-visitar/escolher-o-bilhete/"]  # not the reseller, not the PDF


def test_page_text_drops_scripts():
    text = op.page_text(HOME)
    assert "Bem-vindo" in text and "€99" not in text


def test_verify_accepts_only_verbatim_adult_prices():
    text = op.page_text(PRICES)
    good = op.OfficialPrice(found=True, amount=17, currency="EUR", quote="Bilhete Adulto — 17€")
    assert op.verify(good, text, "attraction").amount == 17
    wrong_number = good.model_copy(update={"amount": 18})
    assert op.verify(wrong_number, text, "attraction") is None
    invented = good.model_copy(update={"quote": "Adult ticket 17€"})
    assert op.verify(invented, text, "attraction") is None                     # not on the page
    senior = op.OfficialPrice(found=True, amount=14, currency="EUR", quote="Seniores > 65 anos — 14€")
    assert op.verify(senior, text, "attraction") is None                       # a reduced price, not the adult one
    child_free = op.OfficialPrice(found=True, free=True, quote="Crianças até 12 anos — Gratuito")
    assert op.verify(child_free, text, "attraction") is None                   # free for children != free entry


def test_official_price_follows_the_price_link(monkeypatch):
    pages = {"https://castelodesaojorge.pt/": HOME,
             "https://castelodesaojorge.pt/como-visitar/escolher-o-bilhete/": PRICES}

    async def fetch_page(url, ttl_s=0):
        if url not in pages:
            raise net.ProviderError("404")
        return {"url": url, "html": pages[url]}

    seen = []

    async def parse(system, user, schema, max_tokens=16000, effort=None, timeout=None):
        seen.append(user)
        return op.OfficialPrice(found=True, amount=17, currency="EUR", quote="Bilhete Adulto — 17€", what="adult")

    monkeypatch.setattr(net, "fetch_page", fetch_page)
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "parse", parse)
    res = anyio.run(op.official_price, "Castelo de São Jorge", "attraction", "https://castelodesaojorge.pt/")
    assert res["amount"] == 17 and res["currency"] == "EUR" and res["page"].endswith("escolher-o-bilhete/")
    assert "Escolher o bilhete" in seen[0]  # the model read the price page first


def _place(pid, name, kind, website=None, **kw):
    return Place(id=pid, name=name, kind=kind, location=GeoPoint(lat=38.71, lon=-9.13), website=website,
                 cost_per_person=Money(amount=18, currency="USD"), metadata=Metadata(source="t", provider="t"), **kw)


class FakeHub:
    async def call(self, server, tool, args):
        assert (server, tool) == ("knowledge", "get_official_price")
        if args["name"] == "Castelo":
            return {"result": {"amount": 17.0, "currency": "EUR", "quote": "Bilhete Adulto — 17€", "what": "adult",
                               "free": False, "page": "https://castelodesaojorge.pt/bilhete/"}}
        if args["name"] == "Taberna":
            return {"result": {"amount": 12.0, "amount_max": 18.0, "currency": "EUR", "quote": "12€", "free": False,
                               "page": "https://taberna.pt/menu"}}
        return {"result": None}


def test_cascade_official_then_ai_then_coverage(monkeypatch):
    b = ResearchBundle(
        attractions=[_place("a1", "Castelo", "attraction", "https://castelodesaojorge.pt/", reviews_count=90000),
                     _place("a2", "Miradouro", "attraction", None),
                     _place("a3", "Museu X", "attraction", "https://museux.pt/")],
        restaurants=[_place("r1", "Taberna", "restaurant", "https://taberna.pt/", reviews_count=900)],
        fx_rates={"USD": 1.0, "EUR": 1.1}, fares={"transit": 2.0, "taxi_base": 4.0, "taxi_per_km": 1.5},
        destination_info={"currency": "EUR", "name": "Lisbon", "country": "Portugal"})

    async def estimate(city, country, local, places, need_transit, need_taxi):
        # Runs alongside the official checks, so it is asked about every unpriced place...
        assert {p["name"] for p in places} == {"Castelo", "Miradouro", "Museu X", "Taberna"}
        return ai_fallback.CityPriceGuess(currency="EUR", transit_single_ticket=1.8, places=[
            ai_fallback.PriceGuess(name="Castelo", amount=12, basis="adult ticket"),  # ...but the official price wins
            ai_fallback.PriceGuess(name="Miradouro", amount=0, basis="free public viewpoint", confidence="high"),
            ai_fallback.PriceGuess(name="Museu X", amount=8, basis="adult ticket", confidence="low")])

    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(ai_fallback, "estimate_prices", estimate)
    contract = TripContract(destination="Lisbon", start_date="2026-11-17", end_date="2026-11-21", budget=Budget(amount=1500))
    anyio.run(pricing.research_prices, FakeHub(), b, contract)
    castelo, mirad, museu = b.attractions
    assert castelo.cost_per_person.price_type == "known" and castelo.cost_per_person.amount == 17
    assert castelo.cost_per_person.source.startswith("Official website (castelodesaojorge.pt)")
    taberna = b.restaurants[0]
    assert taberna.cost_per_person.price_type == "range" and taberna.cost_per_person.amount == 15  # mid of mains 12-18
    assert museu.cost_per_person.price_type == "estimated" and "low confidence" in museu.cost_per_person.source
    assert mirad.cost_per_person.amount == 0 and mirad.cost_per_person.source.startswith("AI estimate")
    assert b.fares["transit"] == 1.98 and b.fares["transit_ai"] == 1.0 and "transit_verified" not in b.fares
    cov = b.price_coverage["attractions"]
    assert cov["verified"] == 1 and cov["official"] == 1 and cov["ai"] == 2
