# -*- coding: utf-8 -*-
"""Datové modely AT Product Scout: tři karty pod dohledem supervizora."""

from __future__ import annotations

import re
from typing import Literal, Optional
from urllib.parse import quote_plus, urlparse

from pydantic import BaseModel, Field, field_validator, model_validator

Badge = Literal[
    "NEJLEVNĚJŠÍ FUNKČNÍ VOLBA",
    "NEJLEPŠÍ CENA / VÝKON",
    "MODERNÍ TREND / INOVACE",
]

BADGE_ORDER: tuple[Badge, ...] = (
    "NEJLEVNĚJŠÍ FUNKČNÍ VOLBA",
    "NEJLEPŠÍ CENA / VÝKON",
    "MODERNÍ TREND / INOVACE",
)

Priority = Literal["cheapest_possible", "balanced", "premium_brands"]

OfferOrigin = Literal[
    "Lokální rakouský e-shop",
    "EU sklad",
    "Direct výrobce",
    "Globální výrobce s doručením do AT",
]

PRIORITY_LABELS: dict[Priority, str] = {
    "cheapest_possible": "Maximální úspora – rozhoduje nejnižší funkční cena.",
    "balanced": "Vyvážený výběr – cena proti výdrži a výbavě.",
    "premium_brands": "Značkové modely – zavedení výrobci s dostupným servisem.",
}

Liquidity = Literal[
    "Vysoká (prodá se do týdne)",
    "Střední poptávka",
    "Nízká (leží měsíce)",
]

GEIZHALS_SEARCH = "https://geizhals.at/?fs={query}"
IDEALO_SEARCH = (
    "https://www.idealo.at/preisvergleich/MainSearchProductCategory.html?q={query}"
)
WILLHABEN_SEARCH = (
    "https://www.willhaben.at/iad/kaufen-und-verkaufen/marktplatz?keyword={query}"
)

BANNED_PRIVATE_BRANDS: tuple[str, ...] = (
    "silvercrest",
    "parkside",
    "ambiano",
    "quigg",
    "crivit",
    "livarno",
    "ernesto",
    "auriol",
    "workzone",
    "casalux",
    "ciao",
)

_SEARCH_NOISE = {
    "kaffeevollautomat",
    "espressomaschine",
    "kaffeemaschine",
    "siebtragermaschine",
    "siebtraegermaschine",
    "siebträgermaschine",
    "kávovar",
    "kavovar",
    "automat",
    "automatický",
    "edelstahl",
    "nerez",
    "schwarz",
    "weiß",
    "weiss",
    "white",
    "black",
    "silber",
}

# Fráze, které supervizor musí přepsat na měřitelné parametry.
BANNED_PHRASES: tuple[str, ...] = (
    "revoluč",
    "špičkov",
    "bezkonkurenč",
    "nejlepší na trhu",
    "jednička na trhu",
    "ideální volba",
    "skvělá volba",
    "vysoká kvalita",
    "vysoce kvalitní",
    "kvalitní zpracování",
    "prémiová kvalita",
    "must-have",
    "nadčasov",
    "perfektní",
    "úžasn",
    "neuvěřitel",
    "spolehlivý pomocník",
    "pro každého",
    "vše, co potřebujete",
    "nejmodernější technologie",
)


# Cena má vlastní pole, v odrážce výhod je to vata místo parametru.
PRICE_FILLERS: tuple[str, ...] = (
    "eur",
    "€",
    "nízká cen",
    "nízkou cen",
    "nízké cen",
    "pořizovací cen",
    "cenově dostupn",
    "dostupná cen",
    "výhodná cen",
    "dobrá cen",
    "příznivá cen",
    "levný model",
    "levná varianta",
    "nejnižší cen",
    "za málo peněz",
)


def find_price_fillers(*texts: str) -> list[str]:
    """Najde odrážky, které místo parametru jen opakují cenu."""
    haystack = " ".join(text for text in texts if text).lower()
    return sorted(phrase for phrase in PRICE_FILLERS if phrase in haystack)


def clean_search_query(original_title: str) -> str:
    """Nechá výrobce a model, zahodí marketingový přívlastky a rozbité znaky."""
    text = original_title.replace("\u00a0", " ")
    text = re.sub(r'[«»“”"„]', "", text)
    text = re.sub(r"[|/]+", " ", text)
    text = re.sub(r"[^\w.+'\- ]+", " ", text, flags=re.UNICODE)
    tokens = [token for token in text.split() if token]
    kept = [token for token in tokens if token.lower().strip(".,") not in _SEARCH_NOISE]
    return " ".join(kept or tokens)


def marketplace_urls(original_title: str) -> dict[str, str]:
    """Přímé vyhledávání na Geizhals, Idealo a Willhaben podle vyčištěného názvu."""
    query = quote_plus(clean_search_query(original_title))
    return {
        "url": GEIZHALS_SEARCH.format(query=query),
        "idealo_url": IDEALO_SEARCH.format(query=query),
        "willhaben_url": WILLHABEN_SEARCH.format(query=query),
    }


def geizhals_search_url(original_title: str) -> str:
    """Vyhledávání na Geizhals.at. Není to přímá nabídka."""
    return marketplace_urls(original_title)["url"]


_SEARCH_HOSTS = {
    "google.com",
    "google.at",
    "google.de",
    "duckduckgo.com",
    "bing.com",
    "search.yahoo.com",
}


def assert_direct_offer_url(url: str) -> str:
    """Nechá jen přímou stránku nabídky, ne výsledky vyhledávače."""
    cleaned = _clean(url)
    parsed = urlparse(cleaned)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    if parsed.scheme not in {"http", "https"} or not host:
        raise ValueError("url musí být přímý http(s) odkaz na nabídku.")
    if host in _SEARCH_HOSTS or host.endswith(".google.com"):
        raise ValueError("url nesmí vést na vyhledávač, ale na stránku nabídky.")
    if host in {"example.com", "example.org", "localhost"}:
        raise ValueError("url musí být reálná stránka nabídky.")
    path = parsed.path.lower()
    if host.endswith("bing.com") and ("aclick" in path or path.startswith("/ck/")):
        raise ValueError("url nesmí být reklamní přesměrování, ale stránka nabídky.")
    if "doubleclick." in host or host.endswith("googleadservices.com"):
        raise ValueError("url nesmí být reklamní přesměrování, ale stránka nabídky.")
    if host.endswith("google.com") and path.startswith("/aclk"):
        raise ValueError("url nesmí být reklamní přesměrování, ale stránka nabídky.")

    query = parsed.query.lower()
    path = parsed.path.lower()
    if "geizhals." in host and ("fs=" in query or path in {"", "/"}):
        raise ValueError("url nesmí být vyhledávání Geizhals. Uveď přímou nabídku prodejce.")
    if "idealo." in host and "mainsearchproductcategory" in path:
        raise ValueError("url nesmí být vyhledávání Idealo. Uveď přímou nabídku prodejce.")
    if "willhaben.at" in host and "keyword=" in query:
        raise ValueError("url nesmí být vyhledávání Willhaben. Bazar má vlastní tlačítko.")
    if "amazon." in host and path.startswith("/s"):
        raise ValueError("url nesmí být vyhledávání Amazonu, ale karta produktu.")
    return cleaned


def find_banned_brands(*texts: str) -> list[str]:
    """Najde privátní značky diskontů, které do verdiktu nepatří."""
    haystack = " ".join(text for text in texts if text).lower()
    return sorted(brand for brand in BANNED_PRIVATE_BRANDS if brand in haystack)


def find_cliches(*texts: str) -> list[str]:
    """Najde marketingová klišé, aby je supervizor nahradil parametry."""
    haystack = " ".join(text for text in texts if text).lower()
    return sorted(phrase for phrase in BANNED_PHRASES if phrase in haystack)


def _clean(value: str) -> str:
    return " ".join(value.split())


class ScoutRequest(BaseModel):
    """Vstup z mobilní aplikace."""

    query: str = Field(
        min_length=1,
        max_length=500,
        description="Nákupní dotaz uživatele, v češtině nebo němčině.",
        examples=["Espresso kávovar do kanceláře"],
    )
    max_budget: Optional[float] = Field(
        default=None,
        gt=0,
        le=1_000_000,
        description="Cenový strop v EUR. Bez hodnoty znamená bez limitu.",
        examples=[250.0],
    )
    priority: Priority = Field(
        default="balanced",
        description="Nákupní strategie: cheapest_possible, balanced nebo premium_brands.",
    )

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        normalized = _clean(value)
        if not normalized:
            raise ValueError("Dotaz nesmí být prázdný.")
        return normalized

    @field_validator("max_budget")
    @classmethod
    def round_budget(cls, value: Optional[float]) -> Optional[float]:
        return None if value is None else round(float(value), 2)


class CandidateIdea(BaseModel):
    """Jeden návrh sub-agenta ve fázi 1."""

    original_title: str = Field(
        description=(
            "Přesný název výrobce a modelu, dohledatelný na webu výrobce nebo prodejce. "
            "Nevymýšlej katalogová čísla ani neexistující řady."
        )
    )
    estimated_price_eur: float = Field(
        gt=0,
        description="Aktuální cena této konkrétní nabídky v EUR, z živého výsledku hledání.",
    )
    hard_fact: str = Field(
        description="Jeden měřitelný technický parametr, ne marketingová fráze."
    )
    weak_spot: str = Field(description="Konkrétní slabina nebo chybějící funkce modelu.")
    offer_url: str = Field(
        description=(
            "Přímá URL stránky produktu u prodejce, zkopírovaná z živých výsledků. "
            "Ne vyhledávání Geizhals, Idealo, Google ani Willhaben."
        )
    )
    offer_origin: OfferOrigin = Field(
        description=(
            "Původ nabídky: 'Lokální rakouský e-shop', 'EU sklad', "
            "'Direct výrobce' nebo 'Globální výrobce s doručením do AT'."
        )
    )
    ship_from_country: str = Field(
        min_length=2,
        max_length=40,
        description="Země odeslání česky, například Rakousko, Německo nebo Nizozemsko.",
    )

    @model_validator(mode="after")
    def normalize_candidate(self) -> CandidateIdea:
        title = _clean(self.original_title)
        country = _clean(self.ship_from_country)
        if len(title) < 3 or not country:
            raise ValueError("Kandidát musí mít model a zemi odeslání.")
        self.original_title = title
        self.hard_fact = _clean(self.hard_fact)
        self.weak_spot = _clean(self.weak_spot)
        self.ship_from_country = country
        self.offer_url = assert_direct_offer_url(self.offer_url)
        self.estimated_price_eur = round(float(self.estimated_price_eur), 2)
        return self


class BudgetScanResult(BaseModel):
    """Výstup sub-agenta 1: rozpočtář a diskontní hlídač."""

    strategy_note: str = Field(
        description="Kde leží cenové dno spolehlivých nabídek s doručením do Rakouska a proč."
    )
    candidates: list[CandidateIdea] = Field(
        min_length=2,
        max_length=4,
        description=(
            "Nejlevnější ještě spolehlivé certifikované modely s doručením do Rakouska, "
            "včetně EU skladu nebo výrobce, když jsou výrazně výhodnější."
        ),
    )


class MarketScanResult(BaseModel):
    """Výstup sub-agenta 2: tržní arbitr přes otevřený internet."""

    market_note: str = Field(
        description="Cenová hladina kategorie na otevřeném webu, včetně EU skladů a výrobců."
    )
    value_candidates: list[CandidateIdea] = Field(
        min_length=2,
        max_length=4,
        description="Modely s nejlepším poměrem spolehlivost/užitná hodnota a doručením do AT.",
    )
    trend_candidates: list[CandidateIdea] = Field(
        min_length=1,
        max_length=3,
        description="Aktuální inovace nebo technologický trend v této kategorii.",
    )


class ResaleRule(BaseModel):
    """Jedno pravidlo bazarové hodnoty pro skupinu značek."""

    brand_tier: str = Field(
        description="Skupina zavedených značek, například vstupní řada DeLonghi nebo Philips."
    )
    residual_share_percent: float = Field(
        gt=0,
        le=100,
        description="Kolik procent nové ceny zbyde po roce na Willhaben.at.",
    )
    liquidity: Liquidity = Field(description="Jak rychle se v Rakousku prodá.")
    reasoning: str = Field(description="Čím je ta hodnota daná: díly, servis, poptávka.")


class ResaleScanResult(BaseModel):
    """Výstup sub-agenta 3: bazarový analytik Willhaben.at."""

    category_note: str = Field(
        description="Jak kategorie celkově drží hodnotu na rakouském bazaru."
    )
    rules: list[ResaleRule] = Field(
        min_length=2,
        max_length=4,
        description="Pravidla zůstatkové hodnoty podle skupiny značek.",
    )


class EvaluatedItem(BaseModel):
    """Jedna ze tří finálních karet."""

    badge: Badge = Field(
        description=(
            "Přesně jedna kategorie: 'NEJLEVNĚJŠÍ FUNKČNÍ VOLBA', "
            "'NEJLEPŠÍ CENA / VÝKON' nebo 'MODERNÍ TREND / INOVACE'."
        )
    )
    name_cz: str = Field(
        description=(
            "Výstižný český název, který obsahuje výrobce i konkrétní model. "
            "Samotná kategorie bez značky je zakázaná."
        )
    )
    original_title: str = Field(
        description=(
            "Přesný název výrobce a modelu, dohledatelný u prodejce. "
            "Nevymýšlej artikl, u nejisté varianty uveď oficiální název řady."
        )
    )
    estimated_price_eur: float = Field(
        gt=0,
        description=(
            "Aktuální cena nalezené nabídky v EUR. "
            "Když živý úryvek uvádí cenu, použij ji. Dopravné do AT připočti jen tehdy, "
            "když je v podkladech uvedené zvlášť."
        ),
    )
    pros: list[str] = Field(
        min_length=3,
        max_length=3,
        description=(
            "Přesně tři konkrétní technická fakta a výhody s čísly nebo parametry. "
            "Žádná marketingová klišé."
        ),
    )
    cons: list[str] = Field(
        min_length=2,
        max_length=2,
        description=(
            "Přesně dva tvrdé kompromisy: co model neumí, kde šetří materiál "
            "nebo jaký má provozní náklad."
        ),
    )
    verdict_target: str = Field(
        description="Pro koho přesně je tato volba určena a pro koho naopak ne."
    )
    willhaben_used_price_eur: float = Field(
        gt=0,
        description=(
            "Reálný odhad ceny zachovalého kusu na Willhaben.at v EUR. "
            "Musí být nižší než estimated_price_eur."
        ),
    )
    willhaben_liquidity: Liquidity = Field(
        description="Jak rychle se model na Willhaben.at prodá."
    )
    offer_origin: OfferOrigin = Field(
        description=(
            "Původ nalezené nabídky: 'Lokální rakouský e-shop', 'EU sklad', "
            "'Direct výrobce' nebo 'Globální výrobce s doručením do AT'."
        )
    )
    ship_from_country: str = Field(
        min_length=2,
        max_length=40,
        description="Země, odkud prodejce zboží odesílá, česky.",
    )
    url: str = Field(
        description=(
            "Přímá URL konkrétní nabídky z živého hledání. "
            "Stránka produktu u prodejce, ne výsledky vyhledávače."
        )
    )
    idealo_url: str = Field(
        default="",
        description=(
            "Vyhledávací odkaz na Idealo.at: "
            "https://www.idealo.at/preisvergleich/MainSearchProductCategory.html?q="
        ),
    )
    willhaben_url: str = Field(
        default="",
        description=(
            "Vyhledávací odkaz na Willhaben.at: "
            "https://www.willhaben.at/iad/kaufen-und-verkaufen/marktplatz?keyword="
        ),
    )

    @model_validator(mode="after")
    def normalize_card(self) -> EvaluatedItem:
        title = _clean(self.original_title)
        if len(title) < 3:
            raise ValueError("original_title musí být konkrétní výrobce a model.")

        name = _clean(self.name_cz)
        target = _clean(self.verdict_target)
        if not name or not target:
            raise ValueError("name_cz a verdict_target nesmí být prázdné.")

        pros = [_clean(entry) for entry in self.pros]
        cons = [_clean(entry) for entry in self.cons]
        if not all(pros) or not all(cons):
            raise ValueError("Odrážky výhod a kompromisů nesmí být prázdné.")

        country = _clean(self.ship_from_country)
        if not country:
            raise ValueError("ship_from_country nesmí být prázdná.")

        self.name_cz = name
        self.original_title = title
        self.verdict_target = target
        self.pros = pros
        self.cons = cons
        self.ship_from_country = country
        self.estimated_price_eur = round(float(self.estimated_price_eur), 2)
        self.willhaben_used_price_eur = round(float(self.willhaben_used_price_eur), 2)
        # Přímou nabídku model nesmí ztratit. Kód doplní jen kontrolu bazaru.
        self.url = assert_direct_offer_url(self.url)
        links = marketplace_urls(title)
        self.idealo_url = links["idealo_url"]
        self.willhaben_url = links["willhaben_url"]
        return self


class FinalReport(BaseModel):
    """Verdikt pro mobilní aplikaci: tři karty a razítko supervizora."""

    items: list[EvaluatedItem] = Field(
        min_length=3,
        max_length=3,
        description=(
            "Přesně tři karty v tomto pořadí: NEJLEVNĚJŠÍ FUNKČNÍ VOLBA, "
            "NEJLEPŠÍ CENA / VÝKON, MODERNÍ TREND / INOVACE."
        ),
    )
    supervisor_verdict: str = Field(
        min_length=1,
        max_length=600,
        description=(
            "Stručné razítko supervizora: rozpočet, přímé nabídky s doručením do AT "
            "a země odeslání. Bez marketingových frází."
        ),
    )

    @model_validator(mode="after")
    def enforce_card_order(self) -> FinalReport:
        found = {item.badge for item in self.items}
        if found != set(BADGE_ORDER):
            raise ValueError(
                "Verdikt musí obsahovat každou kategorii právě jednou: "
                + ", ".join(BADGE_ORDER)
            )
        order = {badge: index for index, badge in enumerate(BADGE_ORDER)}
        self.items = sorted(self.items, key=lambda item: order[item.badge])
        self.supervisor_verdict = _clean(self.supervisor_verdict)
        if not self.supervisor_verdict:
            raise ValueError("supervisor_verdict nesmí být prázdný.")
        return self
