# -*- coding: utf-8 -*-
"""Datové modely AT Product Scout: tři karty pod dohledem supervizora."""

from __future__ import annotations

from typing import Literal, Optional
from urllib.parse import quote_plus

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


def geizhals_search_url(original_title: str) -> str:
    """Vyhledávání na Geizhals.at. Produktový slug se nepoužívá, končí 404."""
    return GEIZHALS_SEARCH.format(query=quote_plus(" ".join(original_title.split())))


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
            "Přesný německý název výrobce a modelu, jak ho najde Geizhals.at. "
            "Nevymýšlej katalogová čísla ani neexistující řady."
        )
    )
    estimated_price_eur: float = Field(
        gt=0, description="Odhad běžné maloobchodní ceny v Rakousku v EUR."
    )
    hard_fact: str = Field(
        description="Jeden měřitelný technický parametr, ne marketingová fráze."
    )
    weak_spot: str = Field(description="Konkrétní slabina nebo chybějící funkce modelu.")


class BudgetScanResult(BaseModel):
    """Výstup sub-agenta 1: rozpočtář a diskontní hlídač."""

    strategy_note: str = Field(
        description="Kde v Rakousku leží cenové dno této kategorie a proč."
    )
    candidates: list[CandidateIdea] = Field(
        min_length=2,
        max_length=4,
        description="Nejlevnější ještě funkční modely včetně privátních značek.",
    )


class MarketScanResult(BaseModel):
    """Výstup sub-agenta 2: tržní arbitr pro Geizhals a Idealo."""

    market_note: str = Field(
        description="Cenová hladina kategorie na Geizhals.at a Idealo.at."
    )
    value_candidates: list[CandidateIdea] = Field(
        min_length=2,
        max_length=4,
        description="Modely s nejlepším poměrem cena/výkon na rakouském trhu.",
    )
    trend_candidates: list[CandidateIdea] = Field(
        min_length=1,
        max_length=3,
        description="Aktuální inovace nebo technologický trend v této kategorii.",
    )


class ResaleRule(BaseModel):
    """Jedno pravidlo bazarové hodnoty pro skupinu značek."""

    brand_tier: str = Field(
        description="Skupina značek, například 'privátní značky Lidl/Hofer' nebo 'De'Longhi'."
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
            "Přesný německý název výrobce a modelu pro srovnávače. "
            "Nevymýšlej artikl, u nejisté varianty uveď oficiální název řady."
        )
    )
    estimated_price_eur: float = Field(
        gt=0,
        description=(
            "Odhad běžné maloobchodní ceny v Rakousku v EUR, "
            "včetně typického dopravného, aby v čísle nebyl skrytý poplatek."
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
    url: str = Field(
        description=(
            "Vyhledávací odkaz na Geizhals.at ve formátu "
            "https://geizhals.at/?fs= plus URL-encoded original_title. "
            "Nikdy přímá adresa produktové karty."
        )
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

        self.name_cz = name
        self.original_title = title
        self.verdict_target = target
        self.pros = pros
        self.cons = cons
        self.estimated_price_eur = round(float(self.estimated_price_eur), 2)
        self.willhaben_used_price_eur = round(float(self.willhaben_used_price_eur), 2)
        self.url = geizhals_search_url(title)
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
            "Stručné razítko supervizora: potvrzení rozpočtu a ověření, "
            "že modely jsou dostupné na rakouském trhu. Bez marketingových frází."
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
