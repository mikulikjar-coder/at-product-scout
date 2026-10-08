# -*- coding: utf-8 -*-
"""AT Product Scout API: sub-agenti generují, nezávislý supervizor schvaluje."""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import TypeVar

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from openai import (
    APIError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    ContentFilterFinishReasonError,
    LengthFinishReasonError,
    RateLimitError,
)
from pydantic import BaseModel, ValidationError

from schemas import (
    BANNED_PHRASES,
    PRIORITY_LABELS,
    BudgetScanResult,
    FinalReport,
    MarketScanResult,
    ResaleScanResult,
    ScoutRequest,
    find_banned_brands,
    find_cliches,
    find_price_fillers,
)

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("at-product-scout")

_API_KEY = os.getenv("OPENAI_API_KEY")
if not _API_KEY:
    raise ValueError("OPENAI_API_KEY nebyl nalezen v .env souboru.")

MODEL = "gpt-4o-mini"
VERDICT_LIMIT = 600

# Pod 85 % ceny z fáze 1 už nejde o zpřesnění, ale o ohnutí odhadu.
PRICE_TOLERANCE = 0.85

_FULL_AUTO_QUERY = (
    "kávovar do kancelář",
    "kavovar do kancelar",
    "espresso automat",
    "kaffeevollautomat",
    "plně automat",
    "plne automat",
    "vollautomat",
)
_OFFICE_HINTS = ("kancelář", "kancelar", "büro", "buero", "office")
_COFFEE_HINTS = ("kávovar", "kavovar", "kaffee", "espresso")
_FORBIDDEN_WHEN_FULL_AUTO = (
    "pákov",
    "pakov",
    "siebträger",
    "siebtrager",
    "portafilter",
    "kapsle",
    "kapsel",
    "nespresso",
    "dolce gusto",
    "tassimo",
    "dedica",
    "stilosa",
)


def requires_full_auto(query: str) -> bool:
    """Kancelářský kávovar a espresso automat musí být Kaffeevollautomat s mlýnkem."""
    lowered = query.lower()
    if any(hint in lowered for hint in _FULL_AUTO_QUERY):
        return True
    coffee = any(hint in lowered for hint in _COFFEE_HINTS)
    office = any(hint in lowered for hint in _OFFICE_HINTS)
    return coffee and office

client = AsyncOpenAI(api_key=_API_KEY, timeout=90.0)

_TModel = TypeVar("_TModel", bound=BaseModel)

_BANNED_LIST = ", ".join(BANNED_PHRASES)

MASTER_SYSTEM_PROMPT = """
Jsi "AT Product Scout Core Engine" – nekompromisní rakouský nákupní analytik
pro rakouský trh (Geizhals.at, Idealo.at, Willhaben.at).

Pravidla:
- Kategorická přesnost: Pokud uživatel hledá "kávovar do kanceláře" nebo
  "espresso automat", MUSÍ to být Kaffeevollautomat s mlýnkem, NIKDY pákový
  kávovar ani kapsle.
- Zákaz privátních značek diskontů: NIKDY nedoporučuj Silvercrest, Parkside
  ani jiné privátní značky, které nejsou běžně na Geizhals.at. Používej pouze
  zavedené značky s plnou distribucí v Rakousku.
- Žádná marketingová klišé: Uveď přesné technické parametry a konkrétní
  kompromisy.
- Reálné odhady Willhaben cen a likvidity pro Rakousko.
""".strip()

_SHARED_RULES = f"""
{MASTER_SYSTEM_PROMPT}

Pevná pravidla pro celou pipeline:
- Nevymýšlej značky, modelové řady ani katalogová čísla. U nejisté varianty
  uveď oficiální název řady, který jde dohledat na Geizhals.at.
- Pracuj jen s produkty reálně dostupnými v Rakousku
  (Geizhals.at, Idealo.at, Amazon.de s doručením do Rakouska, MediaMarkt, Saturn).
- Ceny uváděj v EUR podle rakouské hladiny, včetně typického dopravného.
- Zakázané marketingové fráze: {_BANNED_LIST}.
  Každé tvrzení musí nést parametr, číslo nebo konkrétní chybějící funkci.
- Odrážka výhod nikdy neopakuje cenu ani slovo EUR. Cena má vlastní pole,
  do výhod patří watty, bary, pascaly, litry, decibely, výdrž nebo výbava.
- Odkazy nesestavuj ručně. Pole url, idealo_url a willhaben_url přepíše kód
  na vyhledávání podle vyčištěného názvu modelu.
""".strip()

_BUDGET_AGENT_PROMPT = f"""
Jsi sub-agent 1 pipeline AT Product Scout: ROZPOČTÁŘ.

Hledáš cenové dno, kde produkt ještě spolehlivě funguje. Používej jen zavedené
značky s plnou distribucí na Geizhals.at, například vstupní řady DeLonghi,
Philips, Melitta, Krups, Saeco, Jura, Bosch, Siemens, Miele, Sage, Severin
nebo Cecotec. Zakázané jsou Silvercrest, Parkside, Ambiano, Quigg a další
privátní značky Lidl/Hofer.

Tvoje práce:
- strategy_note: kde v Rakousku leží cenové dno kategorie u zavedených značek.
- candidates: nejlevnější modely zavedených značek, které ještě zvládnou
  hlavní úkol. U každého jeden měřitelný parametr a jedna konkrétní slabina.

{_SHARED_RULES}
""".strip()

_MARKET_AGENT_PROMPT = f"""
Jsi sub-agent 2 pipeline AT Product Scout: TRŽNÍ ARBITR PRO RAKOUSKO.
Pracuješ s cenovou hladinou srovnávačů Geizhals.at a Idealo.at.

Tvoje práce:
- market_note: jak jsou ceny kategorie v Rakousku rozvrstvené.
- value_candidates: modely, kde další eura už nepřinášejí výkon.
- trend_candidates: aktuální inovace kategorie, která se v Rakousku skutečně prodává.

{_SHARED_RULES}
""".strip()

_RESALE_AGENT_PROMPT = f"""
Jsi sub-agent 3 pipeline AT Product Scout: BAZAROVÝ ANALYTIK WILLHABEN.AT,
největšího rakouského inzertního trhu.

Neřeš jednotlivé modely, ale pravidla zůstatkové hodnoty pro skupiny
zavedených značek v této kategorii: kolik procent nové ceny zbyde po roce
a jak rychle se kus prodá. Zohledni dostupnost náhradních dílů, servis
v Rakousku a reálnou poptávku na Willhaben.at.

{_SHARED_RULES}
""".strip()

_SUPERVISOR_PROMPT = f"""
Jsi NEZÁVISLÝ SUPERVIZOR (Gatekeeper / Quality Auditor) pipeline AT Product Scout.
Tři sub-agenti ti poslali podklady. Nevěříš jim na slovo, jsi poslední kontrola
před odesláním dat do mobilní aplikace.

Sestav přesně tři karty a každou proveď tímto kontrolním seznamem:
1. ROZPOČET: karta NEJLEVNĚJŠÍ FUNKČNÍ VOLBA nesmí překročit zadaný strop.
   Pokud podklady strop překračují, vyber skutečně dostupný low-cost model
   zavedené značky, který se pod strop vejde. Nikdy Silvercrest, Parkside
   ani jinou privátní značku diskontu. Ceny přebíráš z podkladů sub-agentů
   a nikdy je nesnižuješ, aby se model do stropu vešel. Když pod strop
   nevejde žádný reálný model zavedené značky, nech nejlevnější dostupný
   kus a do supervisor_verdict napiš, že strop nelze dodržet.
2. KATEGORIE: kávovar do kanceláře nebo espresso automat = jen
   Kaffeevollautomat s integrovaným mlýnkem. Pákový kávovar a kapsle jsou
   v tomhle úkolu zakázané.
3. ŽÁDNÁ KLIŠÉ: zakázané fráze: {_BANNED_LIST}.
   Každá ze tří výhod nese měřitelný parametr, každý ze dvou kompromisů
   pojmenuje chybějící funkci, provozní náklad nebo úsporu na materiálu.
4. CENOVÁ LOGIKA: willhaben_used_price_eur musí být nižší než estimated_price_eur
   a musí odpovídat pravidlům bazarového analytika i zvolené likviditě.
5. ODKAZY: kód je přepíše na vyhledávání Geizhals, Idealo a Willhaben
   podle vyčištěného original_title.
6. POŘADÍ: NEJLEVNĚJŠÍ FUNKČNÍ VOLBA, pak NEJLEPŠÍ CENA / VÝKON,
   pak MODERNÍ TREND / INOVACE.

Do supervisor_verdict napiš jednu věcnou větu do 25 slov: zda rozpočet drží
a že vybrané modely jsou dostupné na rakouském trhu. Žádné superlativy.

{_SHARED_RULES}
""".strip()

_PRIORITY_HINTS: dict[str, str] = {
    "cheapest_possible": (
        "Uživatel chce maximální úsporu. U nejlevnější karty jdi na dno sortimentu "
        "zavedených značek na Geizhals.at. Privátní značky diskontů jsou zakázané."
    ),
    "balanced": (
        "Uživatel chce vyvážený výběr. Nejlevnější karta musí být ještě použitelná, "
        "karta cena/výkon má mít největší přírůstek výbavy za euro."
    ),
    "premium_brands": (
        "Uživatel preferuje zavedené značky se servisem v Rakousku. I nejlevnější "
        "karta má být od výrobce s dostupnými díly, ne bezejmenný import."
    ),
}


def _budget_line(request: ScoutRequest) -> str:
    if request.max_budget is None:
        return "Cenový strop: bez limitu."
    return (
        f"Cenový strop: {request.max_budget:.2f} EUR a karta "
        "NEJLEVNĚJŠÍ FUNKČNÍ VOLBA se pod něj musí vejít."
    )


def _brief(request: ScoutRequest) -> str:
    return (
        f"Uživatel hledá: {request.query}\n"
        f"{_budget_line(request)}\n"
        f"Strategie: {PRIORITY_LABELS[request.priority]}\n"
        f"{_PRIORITY_HINTS[request.priority]}"
    )


class UTF8JSONResponse(JSONResponse):
    media_type = "application/json; charset=utf-8"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    await client.close()


app = FastAPI(
    title="AT Product Scout API",
    description="Sub-agenti generují nabídky, nezávislý supervizor je schvaluje.",
    lifespan=lifespan,
    default_response_class=UTF8JSONResponse,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


async def _parse_structured(
    schema: type[_TModel],
    system_prompt: str,
    user_prompt: str,
    *,
    max_tokens: int,
    temperature: float,
    attempts: int = 2,
) -> _TModel:
    """Jedno volání Structured Outputs. Nevalidní odpověď zkusí ještě jednou."""
    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            completion = await client.beta.chat.completions.parse(
                model=MODEL,
                temperature=temperature,
                max_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": MASTER_SYSTEM_PROMPT},
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format=schema,
            )
        except (ValidationError, LengthFinishReasonError) as exc:
            last_error = exc
            logger.warning("%s: pokus %s neprošel schématem.", schema.__name__, attempt)
            continue

        message = completion.choices[0].message
        if message.refusal:
            raise RuntimeError(f"Model odmítl odpovědět: {message.refusal}")
        if message.parsed is None:
            last_error = RuntimeError("Model nevrátil strukturovaná data.")
            continue
        return message.parsed

    raise RuntimeError(
        f"Model ani po {attempts} pokusech nevrátil platný výstup "
        f"pro {schema.__name__}: {last_error}"
    )


async def run_subagents(
    request: ScoutRequest,
) -> tuple[BudgetScanResult, MarketScanResult, ResaleScanResult]:
    """Fáze 1: tři sub-agenti pracují paralelně na vlastním úseku trhu."""
    brief = _brief(request)
    budget_scan, market_scan, resale_scan = await asyncio.gather(
        _parse_structured(
            BudgetScanResult,
            _BUDGET_AGENT_PROMPT,
            f"{brief}\n\nNajdi cenové dno této kategorie v Rakousku.",
            max_tokens=1200,
            temperature=0.3,
        ),
        _parse_structured(
            MarketScanResult,
            _MARKET_AGENT_PROMPT,
            f"{brief}\n\nZmapuj poměr cena/výkon a aktuální inovace kategorie.",
            max_tokens=1400,
            temperature=0.3,
        ),
        _parse_structured(
            ResaleScanResult,
            _RESALE_AGENT_PROMPT,
            f"{brief}\n\nUrči pravidla zůstatkové hodnoty na Willhaben.at.",
            max_tokens=1000,
            temperature=0.3,
        ),
    )
    return budget_scan, market_scan, resale_scan


def _supervisor_brief(
    request: ScoutRequest,
    budget_scan: BudgetScanResult,
    market_scan: MarketScanResult,
    resale_scan: ResaleScanResult,
) -> str:
    return (
        f"{_brief(request)}\n\n"
        f"PODKLAD SUB-AGENTA 1 (rozpočtář):\n{budget_scan.model_dump_json(indent=2)}\n\n"
        f"PODKLAD SUB-AGENTA 2 (tržní arbitr):\n{market_scan.model_dump_json(indent=2)}\n\n"
        f"PODKLAD SUB-AGENTA 3 (Willhaben analytik):\n{resale_scan.model_dump_json(indent=2)}\n\n"
        "Zkontroluj podklady podle svého kontrolního seznamu a vrať finální tři karty."
    )


def reference_prices(
    budget_scan: BudgetScanResult, market_scan: MarketScanResult
) -> dict[str, float]:
    """Ceny z fáze 1 podle modelu, aby supervizor nemohl cenu ohnout."""
    prices: dict[str, float] = {}
    pool = (
        *budget_scan.candidates,
        *market_scan.value_candidates,
        *market_scan.trend_candidates,
    )
    for candidate in pool:
        key = " ".join(candidate.original_title.split()).lower()
        # Nejnižší nalezená cena dává supervizorovi výhodu pochybnosti.
        prices[key] = min(
            prices.get(key, candidate.estimated_price_eur),
            candidate.estimated_price_eur,
        )
    return prices


def audit_report(
    report: FinalReport,
    request: ScoutRequest,
    known_prices: dict[str, float] | None = None,
) -> list[str]:
    """Deterministický audit nad verdiktem supervizora."""
    problems: list[str] = []
    cheapest = report.items[0]

    if request.max_budget is not None and cheapest.estimated_price_eur > request.max_budget:
        problems.append(
            f"Karta NEJLEVNĚJŠÍ FUNKČNÍ VOLBA stojí {cheapest.estimated_price_eur:.2f} EUR "
            f"a překračuje strop {request.max_budget:.2f} EUR. Nahraď ji modelem, "
            "který se pod strop reálně vejde."
        )

    for item in report.items:
        banned = find_banned_brands(item.name_cz, item.original_title)
        if banned:
            problems.append(
                f"Karta '{item.name_cz}' obsahuje zakázanou privátní značku "
                f"({', '.join(banned)}). Nahraď ji zavedenou značkou z Geizhals.at."
            )
        if requires_full_auto(request.query):
            haystack = " ".join(
                (item.name_cz, item.original_title, item.verdict_target, *item.pros, *item.cons)
            ).lower()
            mismatches = [hint for hint in _FORBIDDEN_WHEN_FULL_AUTO if hint in haystack]
            if mismatches:
                problems.append(
                    f"Karta '{item.name_cz}' není Kaffeevollautomat s mlýnkem "
                    f"({', '.join(mismatches)}). Pro tento dotaz je pákový kávovar "
                    "i kapsle zakázané."
                )
        cliches = find_cliches(item.name_cz, item.verdict_target, *item.pros, *item.cons)
        if cliches:
            problems.append(
                f"Karta '{item.name_cz}' obsahuje klišé ({', '.join(cliches)}). "
                "Nahraď je měřitelnými parametry."
            )
        fillers = find_price_fillers(*item.pros)
        if fillers:
            problems.append(
                f"Výhody u karty '{item.name_cz}' jen opakují cenu "
                f"({', '.join(fillers)}). Nahraď je technickým parametrem."
            )
        if item.willhaben_used_price_eur >= item.estimated_price_eur:
            problems.append(
                f"Karta '{item.name_cz}' má bazarovou cenu "
                f"{item.willhaben_used_price_eur:.2f} EUR, což není méně než nová cena "
                f"{item.estimated_price_eur:.2f} EUR."
            )

        quoted = (known_prices or {}).get(item.original_title.lower())
        if quoted is not None and item.estimated_price_eur < quoted * PRICE_TOLERANCE:
            problems.append(
                f"Karta '{item.name_cz}' uvádí {item.estimated_price_eur:.2f} EUR, "
                f"ale sub-agent u stejného modelu hlásil {quoted:.2f} EUR. "
                "Nesnižuj cenu, aby se model vešel do rozpočtu."
            )

    verdict_cliches = find_cliches(report.supervisor_verdict)
    if verdict_cliches:
        problems.append(
            f"Razítko supervizora obsahuje klišé ({', '.join(verdict_cliches)})."
        )

    return problems


def _clamp_resale_prices(report: FinalReport) -> list[str]:
    """Záchranná brzda, když supervizor cenovou logiku neopraví."""
    fixed: list[str] = []
    for item in report.items:
        if item.willhaben_used_price_eur >= item.estimated_price_eur:
            # 65 % nové ceny je spodní hranice obvyklé roční zůstatkové hodnoty v AT.
            item.willhaben_used_price_eur = round(item.estimated_price_eur * 0.65, 2)
            fixed.append(item.name_cz)
    return fixed


def _shorten(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(" ,.;:") + "…"


def _eur(value: float) -> str:
    return f"{value:.2f}".replace(".", ",") + " €"


def _remarks(count: int) -> str:
    if count == 1:
        return "1 připomínka zůstala"
    if count in (2, 3, 4):
        return f"{count} připomínky zůstaly"
    return f"{count} připomínek zůstalo"


def _stamp_verdict(
    report: FinalReport, request: ScoutRequest, unresolved: list[str]
) -> None:
    """Připojí k razítku supervizora fakta, která ověřil kód, ne model."""
    cheapest = report.items[0]

    if request.max_budget is None:
        budget_note = "rozpočet bez limitu"
    elif cheapest.estimated_price_eur <= request.max_budget:
        budget_note = (
            f"rozpočet {_eur(request.max_budget)} dodržen "
            f"(nejlevnější {_eur(cheapest.estimated_price_eur)})"
        )
    else:
        budget_note = (
            f"rozpočet {_eur(request.max_budget)} nelze dodržet, nejlevnější "
            f"funkční model stojí {_eur(cheapest.estimated_price_eur)}"
        )

    if unresolved:
        audit_note = f"Audit s výhradou: {budget_note}, {_remarks(len(unresolved))}."
    else:
        audit_note = (
            f"Audit prošel: {budget_note}, 3 modely ověřeny odkazem na Geizhals.at, "
            "bazarové ceny pod novou cenou."
        )

    own_text = _shorten(report.supervisor_verdict, VERDICT_LIMIT - len(audit_note) - 2)
    report.supervisor_verdict = f"{own_text} {audit_note}".strip()


async def supervise(
    request: ScoutRequest,
    budget_scan: BudgetScanResult,
    market_scan: MarketScanResult,
    resale_scan: ResaleScanResult,
) -> FinalReport:
    """Fáze 2: supervizor sestaví karty, audit je prověří a případně vrátí k opravě."""
    brief = _supervisor_brief(request, budget_scan, market_scan, resale_scan)
    known_prices = reference_prices(budget_scan, market_scan)
    report = await _parse_structured(
        FinalReport,
        _SUPERVISOR_PROMPT,
        brief,
        max_tokens=3200,
        temperature=0.1,
    )

    problems = audit_report(report, request, known_prices)
    if problems:
        logger.warning("Audit našel %s závad, posílám verdikt k opravě.", len(problems))
        repair_brief = (
            f"{brief}\n\n"
            f"TVŮJ PŘEDCHOZÍ VERDIKT:\n{report.model_dump_json(indent=2)}\n\n"
            "Deterministický audit ti ho vrátil. Závady k odstranění:\n"
            + "\n".join(f"- {problem}" for problem in problems)
            + "\n\nOprav je a vrať celý verdikt znovu."
        )
        report = await _parse_structured(
            FinalReport,
            _SUPERVISOR_PROMPT,
            repair_brief,
            max_tokens=3200,
            temperature=0.0,
        )
        problems = audit_report(report, request, known_prices)

    clamped = _clamp_resale_prices(report)
    if clamped:
        logger.warning("Bazarové ceny dorovnány kódem u: %s", ", ".join(clamped))
        problems = audit_report(report, request, known_prices)

    if problems:
        logger.warning("Nevyřešené připomínky auditu: %s", problems)

    _stamp_verdict(report, request, problems)
    return report


@app.post("/api/scout", response_model=FinalReport)
async def scout(payload: ScoutRequest) -> FinalReport:
    logger.info(
        "Scout dotaz: %s | strop: %s | strategie: %s",
        payload.query,
        payload.max_budget,
        payload.priority,
    )
    try:
        budget_scan, market_scan, resale_scan = await run_subagents(payload)
        logger.info(
            "Fáze 1 hotova: %s + %s + %s kandidátů.",
            len(budget_scan.candidates),
            len(market_scan.value_candidates) + len(market_scan.trend_candidates),
            len(resale_scan.rules),
        )
        report = await supervise(payload, budget_scan, market_scan, resale_scan)
        logger.info("Fáze 2 hotova: %s", report.supervisor_verdict)
        return report
    except ValidationError as exc:
        logger.exception("Verdikt neprošel schématem.")
        raise HTTPException(
            status_code=502,
            detail="Supervizor vrátil verdikt, který nesplňuje schéma tří karet.",
        ) from exc
    except RateLimitError as exc:
        raise HTTPException(
            status_code=429,
            detail="Překročen limit OpenAI API. Zkuste to za chvíli.",
        ) from exc
    except APITimeoutError as exc:
        raise HTTPException(
            status_code=504,
            detail="Analýza trhu trvala příliš dlouho.",
        ) from exc
    except ContentFilterFinishReasonError as exc:
        raise HTTPException(
            status_code=400,
            detail="Dotaz neprošel obsahovým filtrem. Zkuste ho přeformulovat.",
        ) from exc
    except AuthenticationError as exc:
        logger.exception("OpenAI autentizace selhala.")
        raise HTTPException(
            status_code=500,
            detail="Služba nákupního analytika není správně nastavená.",
        ) from exc
    except APIError as exc:
        logger.exception("OpenAI API chyba.")
        raise HTTPException(
            status_code=502,
            detail="Služba nákupního analytika je dočasně nedostupná.",
        ) from exc
    except RuntimeError as exc:
        logger.exception("Pipeline selhala.")
        raise HTTPException(status_code=502, detail=str(exc)) from exc


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=False)
