"""The destinations the recommender knows: one Wikivoyage guide each (the training text).

The tags are hand labels (the same interests the UI offers). The model never sees them while training - it
learns from the guide text alone. They are the ground truth for evaluation: a good model ranks beach towns
first for "beach" and puts ski resorts next to other ski resorts.
"""

from __future__ import annotations

from dataclasses import dataclass

INTERESTS = ["beach", "culture", "history", "nature", "ski", "food", "nightlife", "shopping", "relax", "adventure"]

# name | country | tags | Wikivoyage title (when it differs from the name)
_RAW = """
Paris|France|culture history food shopping
Nice|France|beach food relax
Lyon|France|food culture history
Chamonix|France|ski nature adventure
Bordeaux|France|food culture
Marseille|France|beach food culture
Rome|Italy|history culture food
Florence|Italy|culture history food
Venice|Italy|culture history
Milan|Italy|shopping culture food
Naples|Italy|food history
Amalfi|Italy|beach relax food
Cinque Terre|Italy|nature beach food
Dolomites|Italy|ski nature adventure
Sicily|Italy|beach history food
Barcelona|Spain|beach culture food nightlife
Madrid|Spain|culture food nightlife shopping
Seville|Spain|history culture food
Granada|Spain|history culture
Ibiza|Spain|nightlife beach
Mallorca|Spain|beach relax
Tenerife|Spain|beach nature adventure
Lisbon|Portugal|culture food history
Porto|Portugal|food culture history
Algarve|Portugal|beach relax
Madeira|Portugal|nature adventure
London|United Kingdom|culture history shopping nightlife
Edinburgh|United Kingdom|history culture
Scottish Highlands|United Kingdom|nature adventure
Dublin|Ireland|nightlife culture history
Amsterdam|Netherlands|culture nightlife
Brussels|Belgium|food culture history
Bruges|Belgium|history culture
Berlin|Germany|culture history nightlife
Munich|Germany|culture food history
Hamburg|Germany|culture nightlife
Prague|Czech Republic|history culture nightlife
Vienna|Austria|culture history food
Salzburg|Austria|culture history
Innsbruck|Austria|ski nature adventure
St. Anton am Arlberg|Austria|ski adventure|St Anton
Zermatt|Switzerland|ski nature adventure
Interlaken|Switzerland|nature adventure
Zurich|Switzerland|shopping culture
Lucerne|Switzerland|nature culture
Budapest|Hungary|history culture nightlife relax
Krakow|Poland|history culture
Warsaw|Poland|history culture
Copenhagen|Denmark|culture food
Stockholm|Sweden|culture history
Oslo|Norway|culture nature
Bergen|Norway|nature culture
Tromsø|Norway|nature adventure
Helsinki|Finland|culture
Lapland|Finland|nature adventure ski|Finnish Lapland
Reykjavík|Iceland|nature adventure
Tallinn|Estonia|history culture
Riga|Latvia|history culture nightlife
Vilnius|Lithuania|history culture
Athens|Greece|history culture food
Santorini|Greece|beach relax
Mykonos|Greece|beach nightlife
Crete|Greece|beach history food
Rhodes|Greece|beach history
Corfu|Greece|beach relax
Thessaloniki|Greece|food history nightlife
Dubrovnik|Croatia|history beach
Split|Croatia|beach history
Hvar|Croatia|beach nightlife
Plitvice Lakes National Park|Croatia|nature
Kotor|Montenegro|history nature
Ljubljana|Slovenia|culture nature
Lake Bled|Slovenia|nature relax|Bled
Sofia|Bulgaria|history culture
Plovdiv|Bulgaria|history culture
Borovets|Bulgaria|ski nature
Bansko|Bulgaria|ski nature
Varna|Bulgaria|beach nightlife
Bucharest|Romania|history culture nightlife
Brașov|Romania|history nature
Belgrade|Serbia|nightlife history
Sarajevo|Bosnia and Herzegovina|history culture
Tirana|Albania|culture
Albanian Riviera|Albania|beach nature
Valletta|Malta|history culture
Cyprus|Cyprus|beach history
Istanbul|Turkey|history culture food shopping
Cappadocia|Turkey|nature adventure history
Antalya|Turkey|beach history relax
Bodrum|Turkey|beach nightlife
Fethiye|Turkey|beach nature adventure
Pamukkale|Turkey|nature history
Tbilisi|Georgia|culture food history
Batumi|Georgia|beach nightlife
Yerevan|Armenia|history culture
Baku|Azerbaijan|culture history
Cairo|Egypt|history culture shopping
Luxor|Egypt|history culture
Aswan|Egypt|history culture relax
Alexandria|Egypt|history beach food
Sharm El Sheikh|Egypt|beach relax adventure|Sharm el-Sheikh
Hurghada|Egypt|beach relax adventure
Dahab|Egypt|beach adventure relax
Siwa|Egypt|nature relax history|Siwa Oasis
Marrakech|Morocco|culture shopping history food
Fes|Morocco|history culture shopping
Chefchaouen|Morocco|culture nature
Essaouira|Morocco|beach culture
Tunis|Tunisia|history culture
Djerba|Tunisia|beach relax
Zanzibar|Tanzania|beach history relax
Serengeti National Park|Tanzania|nature adventure
Nairobi|Kenya|nature culture
Maasai Mara|Kenya|nature adventure|Maasai Mara National Reserve
Cape Town|South Africa|nature food beach adventure
Kruger National Park|South Africa|nature adventure
Victoria Falls|Zimbabwe|nature adventure
Mauritius|Mauritius|beach relax
Seychelles|Seychelles|beach relax nature
Madagascar|Madagascar|nature adventure
Addis Ababa|Ethiopia|culture history
Dubai|United Arab Emirates|shopping beach nightlife
Abu Dhabi|United Arab Emirates|culture beach shopping
Muscat|Oman|culture history nature
Doha|Qatar|culture shopping
Petra|Jordan|history adventure
Wadi Rum|Jordan|nature adventure
Dead Sea|Jordan|relax nature|Dead Sea (Jordan)
Beirut|Lebanon|food nightlife culture
AlUla|Saudi Arabia|history nature adventure|Al-Ula
Riyadh|Saudi Arabia|culture shopping
Jeddah|Saudi Arabia|culture history beach
Bali|Indonesia|beach culture relax nature
Jakarta|Indonesia|culture shopping
Singapore|Singapore|food shopping culture
Kuala Lumpur|Malaysia|shopping food culture
Langkawi|Malaysia|beach relax nature
Penang|Malaysia|food culture history
Bangkok|Thailand|food nightlife shopping culture
Chiang Mai|Thailand|culture nature food
Phuket|Thailand|beach nightlife
Krabi|Thailand|beach nature adventure|Ao Nang
Koh Samui|Thailand|beach relax
Hanoi|Vietnam|food culture history
Ho Chi Minh City|Vietnam|food nightlife history
Ha Long Bay|Vietnam|nature adventure|Halong Bay
Hoi An|Vietnam|history culture food beach
Siem Reap|Cambodia|history culture
Luang Prabang|Laos|culture relax
Manila|Philippines|culture shopping
Palawan|Philippines|beach nature adventure|El Nido
Boracay|Philippines|beach nightlife
Tokyo|Japan|food culture shopping nightlife
Kyoto|Japan|culture history food
Osaka|Japan|food nightlife shopping
Hokkaido|Japan|ski nature food
Okinawa|Japan|beach relax
Seoul|South Korea|food shopping culture nightlife
Busan|South Korea|beach food
Jeju|South Korea|nature beach
Beijing|China|history culture
Shanghai|China|shopping food nightlife
Hong Kong|China|food shopping nightlife
Taipei|Taiwan|food culture nightlife
Delhi|India|history culture food shopping
Agra|India|history
Jaipur|India|history culture shopping
Goa|India|beach nightlife relax
Kerala|India|nature relax culture
Mumbai|India|food culture nightlife
Varanasi|India|culture history
Ladakh|India|nature adventure
Kathmandu|Nepal|culture history adventure
Pokhara|Nepal|nature adventure relax
Sri Lanka|Sri Lanka|beach nature history
Maldives|Maldives|beach relax
Bhutan|Bhutan|nature culture
Almaty|Kazakhstan|nature ski
Samarkand|Uzbekistan|history culture
Sydney|Australia|beach culture food
Melbourne|Australia|food culture shopping
Great Barrier Reef|Australia|nature beach adventure
Queenstown|New Zealand|adventure nature ski|Queenstown (New Zealand)
Auckland|New Zealand|culture nature
Fiji|Fiji|beach relax
Bora Bora|French Polynesia|beach relax
Hawaii|United States|beach nature relax
New York City|United States|culture shopping food nightlife
Los Angeles|United States|beach culture shopping
San Francisco|United States|culture food
Las Vegas|United States|nightlife shopping
Miami|United States|beach nightlife
Orlando|United States|shopping relax
Chicago|United States|culture food
New Orleans|United States|food nightlife culture
Grand Canyon National Park|United States|nature adventure
Yellowstone National Park|United States|nature adventure
Aspen|United States|ski nature
Washington, D.C.|United States|history culture
Boston|United States|history culture
Vancouver|Canada|nature food
Banff National Park|Canada|nature ski adventure
Whistler|Canada|ski adventure
Toronto|Canada|culture food shopping
Montreal|Canada|culture food nightlife
Quebec City|Canada|history culture
Mexico City|Mexico|culture history food
Cancún|Mexico|beach nightlife
Tulum|Mexico|beach history relax
Oaxaca|Mexico|food culture|Oaxaca (city)
Havana|Cuba|culture history nightlife
Punta Cana|Dominican Republic|beach relax
Jamaica|Jamaica|beach relax
Costa Rica|Costa Rica|nature adventure beach
Cartagena|Colombia|history beach nightlife|Cartagena (Colombia)
Medellín|Colombia|culture nightlife
Cusco|Peru|history culture adventure
Machu Picchu|Peru|history nature adventure
Lima|Peru|food culture
Rio de Janeiro|Brazil|beach nightlife culture
Salvador|Brazil|culture history beach
Buenos Aires|Argentina|culture food nightlife
Patagonia|Argentina|nature adventure|El Calafate
Mendoza|Argentina|food nature
Santiago|Chile|culture food|Santiago (Chile)
Atacama Desert|Chile|nature adventure|San Pedro de Atacama
Galápagos Islands|Ecuador|nature adventure
Uyuni|Bolivia|nature adventure
"""


@dataclass(frozen=True)
class Destination:
    id: str
    name: str
    country: str
    tags: tuple[str, ...]
    wikivoyage: str


def _slug(s: str) -> str:
    import re
    import unicodedata

    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def load() -> list[Destination]:
    out = []
    for line in _RAW.strip().splitlines():
        parts = line.split("|")
        name, country, tags = parts[0], parts[1], tuple(parts[2].split())
        assert all(t in INTERESTS for t in tags), line
        out.append(Destination(id=_slug(name), name=name, country=country, tags=tags,
                               wikivoyage=parts[3] if len(parts) > 3 else name))
    assert len({d.id for d in out}) == len(out), "duplicate destination id"
    return out
