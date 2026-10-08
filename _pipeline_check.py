# -*- coding: utf-8 -*-
"""Deterministická kontrola schémat a auditu bez volání OpenAI."""

from openai.lib._pydantic import to_strict_json_schema

from app import _clamp_resale_prices, _stamp_verdict, audit_report, requires_full_auto
from schemas import (
    BudgetScanResult,
    EvaluatedItem,
    FinalReport,
    MarketScanResult,
    ResaleScanResult,
    ScoutRequest,
    clean_search_query,
    find_cliches,
    find_price_fillers,
    marketplace_urls,
)
from web_search import MarketEvidence, WebHit, canonical_url, extract_prices, is_tracker_url


OFFER_URL = "https://www.mediamarkt.at/de/product/delonghi-ec-685-123456"


def card(badge, name, new_price, used_price, pros=None, cons=None):
    return EvaluatedItem(
        badge=badge,
        name_cz=name,
        original_title=name.split(" ", 1)[-1],
        estimated_price_eur=new_price,
        pros=pros or ["15 barů tlaku", "nádrž 1,8 l", "příkon 1350 W"],
        cons=cons or ["plastové tělo", "hlučnost 78 dB"],
        verdict_target="Pro kancelář do pěti lidí.",
        willhaben_used_price_eur=used_price,
        willhaben_liquidity="Střední poptávka",
        offer_origin="Lokální rakouský e-shop",
        ship_from_country="  Rakousko  ",
        url=OFFER_URL,
    )


# 1. Strict JSON schema pro všechny modely posílané do OpenAI.
for schema in (BudgetScanResult, MarketScanResult, ResaleScanResult, FinalReport):
    to_strict_json_schema(schema)
print("STRICT_SCHEMAS_OK")

# 2. ScoutRequest: rozpočet i priorita.
assert ScoutRequest(query="  kávovar  ").max_budget is None
assert ScoutRequest(query="kávovar").priority == "balanced"
assert ScoutRequest(query="kávovar", max_budget=249.999).max_budget == 250.0
assert ScoutRequest(query="kávovar", priority="premium_brands").priority == "premium_brands"
try:
    ScoutRequest(query="kávovar", max_budget=0)
    raise AssertionError("nulový rozpočet měl selhat")
except Exception:
    pass
print("SCOUT_REQUEST_OK")

# 3. Přímá nabídka zůstane, bazar Willhaben se doplní, vyhledávač se odmítne.
item = card("NEJLEVNĚJŠÍ FUNKČNÍ VOLBA", "Kávovar De'Longhi EC 685", 199.0, 120.0)
links = marketplace_urls("De'Longhi EC 685")
assert item.url == OFFER_URL, item.url
assert item.offer_origin == "Lokální rakouský e-shop"
assert item.ship_from_country == "Rakousko"
assert "geizhals.at/?fs=" not in item.url
assert item.idealo_url.startswith("https://www.idealo.at/"), item.idealo_url
assert item.willhaben_url == links["willhaben_url"]
assert item.willhaben_url.startswith("https://www.willhaben.at/"), item.willhaben_url
assert clean_search_query('De\'Longhi Magnifica S "Kaffeevollautomat" Edelstahl') == (
    "De'Longhi Magnifica S"
)
assert is_tracker_url("https://www.bing.com/aclick?ld=abc")
assert not is_tracker_url(OFFER_URL)
for bad_url in (
    "https://geizhals.at/?fs=kavovar",
    "https://www.google.com/search?q=kavovar",
    "https://example.com/produkt",
    "https://www.bing.com/aclick?ld=abc",
):
    try:
        EvaluatedItem(
            badge="NEJLEVNĚJŠÍ FUNKČNÍ VOLBA",
            name_cz="Kávovar DeLonghi Magnifica",
            original_title="DeLonghi Magnifica",
            estimated_price_eur=199.0,
            pros=["15 barů tlaku", "nádrž 1,8 l", "příkon 1350 W"],
            cons=["plastové tělo", "hlučnost 78 dB"],
            verdict_target="Pro kancelář do pěti lidí.",
            willhaben_used_price_eur=120.0,
            willhaben_liquidity="Střední poptávka",
            offer_origin="EU sklad",
            ship_from_country="Německo",
            url=bad_url,
        )
    except Exception as exc:
        assert "url" in str(exc).lower(), exc
    else:
        raise AssertionError(f"URL {bad_url} měla selhat")
print("URL_NORMALIZACE_OK", item.url)

# 4. Pořadí karet se srovná bez ohledu na vstup.
report = FinalReport(
    items=[
        card("MODERNÍ TREND / INOVACE", "Kávovar Philips 5400", 599.0, 380.0),
        card("NEJLEPŠÍ CENA / VÝKON", "Kávovar Sage Bambino", 329.0, 210.0),
        card("NEJLEVNĚJŠÍ FUNKČNÍ VOLBA", "Kávovar DeLonghi Magnifica S", 89.0, 45.0),
    ],
    supervisor_verdict="Vybrané modely jsou v Rakousku dostupné.",
)
assert [i.badge for i in report.items] == [
    "NEJLEVNĚJŠÍ FUNKČNÍ VOLBA",
    "NEJLEPŠÍ CENA / VÝKON",
    "MODERNÍ TREND / INOVACE",
]
print("PORADI_KARET_OK")

# 5. Počty odrážek jsou vynucené.
for bad_pros, bad_cons in (([
    "jen dvě", "odrážky"], ["a", "b"]), (["a", "b", "c"], ["jen jedna"])):
    try:
        card("NEJLEPŠÍ CENA / VÝKON", "Test Model", 100.0, 50.0, bad_pros, bad_cons)
        raise AssertionError("špatný počet odrážek měl selhat")
    except Exception as exc:
        assert "pros" in str(exc) or "cons" in str(exc), exc
print("POCTY_ODRAZEK_OK")

# 6. Audit: rozpočet, klišé i cenová logika.
clean_request = ScoutRequest(query="kávovar", max_budget=100.0)
assert audit_report(report, clean_request) == []

over_budget = ScoutRequest(query="kávovar", max_budget=50.0)
problems = audit_report(report, over_budget)
assert len(problems) == 1 and "překračuje strop" in problems[0], problems

broken = FinalReport(
    items=[
        card(
            "NEJLEVNĚJŠÍ FUNKČNÍ VOLBA",
            "Kávovar Silvercrest SEMM",
            89.0,
            95.0,  # bazar dražší než nový kus
            ["revoluční výkon", "vysoká kvalita", "perfektní chuť"],
            ["plast", "hlučnost"],
        ),
        card("NEJLEPŠÍ CENA / VÝKON", "Kávovar Sage Bambino", 329.0, 210.0),
        card("MODERNÍ TREND / INOVACE", "Kávovar Philips 5400", 599.0, 380.0),
    ],
    supervisor_verdict="Bezkonkurenční výběr pro každého.",
)
problems = audit_report(broken, over_budget)
joined = " | ".join(problems)
assert "obsahuje klišé" in joined, joined
assert "není méně než nová cena" in joined, joined
assert "Razítko supervizora obsahuje klišé" in joined, joined
assert "zakázanou privátní značku" in joined, joined
print("AUDIT_OK", len(problems), "zavad")

# 7. Záchranná brzda dorovná bazarovou cenu pod novou.
fixed = _clamp_resale_prices(broken)
assert fixed == ["Kávovar Silvercrest SEMM"], fixed
assert broken.items[0].willhaben_used_price_eur < broken.items[0].estimated_price_eur
assert not any("není méně než nová cena" in p for p in audit_report(broken, clean_request))
print("CLAMP_OK", broken.items[0].willhaben_used_price_eur)

# 8. Razítko: dodržený rozpočet, překročený rozpočet i limit délky.
ok_report = report.model_copy(deep=True)
_stamp_verdict(ok_report, clean_request, [])
assert "Audit prošel" in ok_report.supervisor_verdict
assert "rozpočet 100,00 € dodržen (nejlevnější 89,00 €)" in ok_report.supervisor_verdict
print("RAZITKO_OK:", ok_report.supervisor_verdict)

fail_report = report.model_copy(deep=True)
_stamp_verdict(fail_report, over_budget, ["neco"])
assert "Audit s výhradou" in fail_report.supervisor_verdict
assert "nelze dodržet" in fail_report.supervisor_verdict
assert "1 připomínka zůstala" in fail_report.supervisor_verdict
print("RAZITKO_VYHRADA_OK:", fail_report.supervisor_verdict)

long_report = report.model_copy(deep=True)
long_report.supervisor_verdict = "Velmi dlouhé zdůvodnění. " * 60
_stamp_verdict(long_report, clean_request, [])
assert len(long_report.supervisor_verdict) <= 600, len(long_report.supervisor_verdict)
FinalReport.model_validate(long_report.model_dump())
print("DELKA_RAZITKA_OK", len(long_report.supervisor_verdict))

# 9. Detektor klišé nehlásí falešné poplachy na věcném textu.
assert find_cliches("Nádrž 1,8 l, příkon 1350 W, tlak 15 barů.") == []
assert find_cliches("Revoluční a perfektní zážitek") == ["perfektní", "revoluč"]
print("DETEKTOR_KLISE_OK")

# 10. Výhoda nesmí jen opakovat cenu, ta má vlastní pole.
assert find_price_fillers("Tlak 20 barů", "Příkon 850 W") == []
assert find_price_fillers("Nízká cena 49,99 EUR") == ["eur", "nízká cen"]
assert find_price_fillers("Nízká pořizovací cena.") == ["pořizovací cen"]
assert requires_full_auto("kávovar do kanceláře")
assert requires_full_auto("espresso automat")
assert not requires_full_auto("pákový kávovar na espresso")
office_mismatch = FinalReport(
    items=[
        card("NEJLEVNĚJŠÍ FUNKČNÍ VOLBA", "Kávovar DeLonghi Dedica EC685", 89.0, 45.0),
        card("NEJLEPŠÍ CENA / VÝKON", "Kávovar Sage Bambino", 329.0, 210.0),
        card("MODERNÍ TREND / INOVACE", "Kávovar Philips 5400", 599.0, 380.0),
    ],
    supervisor_verdict="Modely jsou v Rakousku dostupné.",
)
office_problems = " | ".join(
    audit_report(office_mismatch, ScoutRequest(query="kávovar do kanceláře"))
)
assert "není Kaffeevollautomat" in office_problems, office_problems
print("KATEGORIE_KAVOVAR_OK")
price_vata = FinalReport(
    items=[
        card(
            "NEJLEVNĚJŠÍ FUNKČNÍ VOLBA",
            "Kávovar DeLonghi Magnifica S",
            89.0,
            45.0,
            ["Příkon 850 W", "Tlak 20 barů", "Cenově dostupný model za 89 EUR"],
            ["plastové tělo", "bez ohřevu mléka"],
        ),
        card("NEJLEPŠÍ CENA / VÝKON", "Kávovar Sage Bambino", 329.0, 210.0),
        card("MODERNÍ TREND / INOVACE", "Kávovar Philips 5400", 599.0, 380.0),
    ],
    supervisor_verdict="Modely jsou v Rakousku dostupné.",
)
filler_problems = audit_report(price_vata, clean_request)
assert len(filler_problems) == 1, filler_problems
assert "jen opakují cenu" in filler_problems[0], filler_problems
# Kompromis smí cenu zmínit, vyšší cena je legitimní nevýhoda.
assert audit_report(report, clean_request) == []
print("DETEKTOR_CENOVE_VATY_OK")

# 11. Živý úryvek drží cenu a URL musí pocházet z nalezených odkazů.
assert extract_prices("heute 1.299,00 € statt 1.499,00 EUR") == [1299.0, 1499.0]
assert extract_prices("EUR 249.90 im Shop") == [249.9]
assert canonical_url("https://www.Shop.AT/p/1/?utm_source=newsletter") == "https://shop.at/p/1"
evidence = MarketEvidence(
    hits=[
        WebHit(
            title="DeLonghi Magnifica S",
            url=OFFER_URL,
            snippet="249,00 €",
            prices_eur=[249.0],
        )
    ]
)
missing = report.model_copy(deep=True)
missing.items[0].url = "https://www.alternate.de/html/product/delonghi-1"
live_problems = audit_report(missing, ScoutRequest(query="kávovar"), evidence=evidence)
assert any("není mezi živě nalezenými odkazy" in problem for problem in live_problems), live_problems
only_first = report.model_copy(deep=True)
only_first.items[0].estimated_price_eur = 249.0
only_first.items[1].url = "https://www.amazon.de/dp/B0TESTVALUE01"
only_first.items[2].url = "https://www.jura.com/de/product/e8-123"
broad = MarketEvidence(
    hits=[
        WebHit(title="MediaMarkt", url=OFFER_URL, snippet="249,00 €", prices_eur=[249.0]),
        WebHit(
            title="Amazon",
            url="https://www.amazon.de/dp/B0TESTVALUE01",
            snippet="329,00 €",
            prices_eur=[329.0],
        ),
        WebHit(
            title="Jura",
            url="https://www.jura.com/de/product/e8-123",
            snippet="599,00 €",
            prices_eur=[599.0],
        ),
    ]
)
assert audit_report(only_first, ScoutRequest(query="kávovar"), evidence=broad) == []
only_first.items[0].estimated_price_eur = 89.0
drift = " | ".join(audit_report(only_first, ScoutRequest(query="kávovar"), evidence=broad))
assert "živý úryvek" in drift, drift
print("ZIVE_PODKLADY_OK")

print("\nALL_DETERMINISTIC_CHECKS_OK")
