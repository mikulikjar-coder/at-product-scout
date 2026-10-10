# -*- coding: utf-8 -*-
"""Deterministická kontrola schémat a auditu bez volání OpenAI."""

import json
import os
import urllib.error
from urllib.parse import unquote_plus

from openai.lib._pydantic import to_strict_json_schema

from app import (
    LIVE_OFFERS_MISSING,
    SerperShoppingError,
    _clamp_resale_prices,
    _stamp_verdict,
    audit_report,
    bind_shortlist,
    parse_serper_shopping,
    prepare_offers,
    requires_full_auto,
    requires_grinder,
    search_serper_shopping,
)
from schemas import (
    BudgetScanResult,
    EvaluatedItem,
    FinalReport,
    MarketScanResult,
    OfferChoice,
    OfferShortlist,
    ResaleScanResult,
    ScoutRequest,
    buy_url_for,
    clean_search_query,
    find_cliches,
    find_price_fillers,
    marketplace_urls,
    shopping_focus,
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
for schema in (BudgetScanResult, MarketScanResult, ResaleScanResult, FinalReport, OfferShortlist):
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

# 3. Nákupní tlačítko je přímý odkaz nabídky. Obecné vyhledávání na Google se neukládá.
item = card("NEJLEVNĚJŠÍ FUNKČNÍ VOLBA", "Kávovar De'Longhi EC 685", 199.0, 120.0)
links = marketplace_urls("De'Longhi EC 685")
assert item.buy_url == OFFER_URL, item.buy_url
assert item.url == OFFER_URL, item.url
assert "google.at/search" not in item.buy_url
assert "hape.com" not in item.url
assert item.offer_origin == "Lokální rakouský e-shop"
assert item.ship_from_country == "Rakousko"
assert item.geizhals_url == links["geizhals_url"]
assert item.geizhals_url.startswith("https://geizhals.at/?fs="), item.geizhals_url
assert item.idealo_url.startswith("https://www.idealo.at/"), item.idealo_url
assert item.willhaben_url == links["willhaben_url"]
assert item.willhaben_url.startswith("https://www.willhaben.at/"), item.willhaben_url
assert clean_search_query('De\'Longhi Magnifica S "Kaffeevollautomat" Edelstahl') == (
    "De'Longhi Magnifica S"
)
assert is_tracker_url("https://www.bing.com/aclick?ld=abc")
assert not is_tracker_url(OFFER_URL)
ghost = EvaluatedItem(
    badge="NEJLEVNĚJŠÍ FUNKČNÍ VOLBA",
    name_cz="Dřevěná dráha Hape E0403",
    original_title="Hape E0403",
    estimated_price_eur=49.0,
    pros=["délka dráhy 120 cm", "bukové dřevo", "věk od 3 let"],
    cons=["bez autíček", "není skládací"],
    verdict_target="Pro děti od tří let.",
    willhaben_used_price_eur=25.0,
    willhaben_liquidity="Střední poptávka",
    offer_origin="EU sklad",
    ship_from_country="Německo",
    url="https://www.hape.com/at/de/e0403",
)
assert ghost.buy_url == "https://www.hape.com/at/de/e0403", ghost.buy_url
assert ghost.url == ghost.buy_url
assert "google.at/search" not in ghost.url
search_only = EvaluatedItem(
    badge="NEJLEVNĚJŠÍ FUNKČNÍ VOLBA",
    name_cz="Dřevěná dráha Hape E0403",
    original_title="Hape E0403",
    estimated_price_eur=49.0,
    pros=["délka dráhy 120 cm", "bukové dřevo", "věk od 3 let"],
    cons=["bez autíček", "není skládací"],
    verdict_target="Pro děti od tří let.",
    willhaben_used_price_eur=25.0,
    willhaben_liquidity="Střední poptávka",
    offer_origin="EU sklad",
    ship_from_country="Německo",
    url="https://www.google.at/search?tbm=shop&q=Hape+E0403",
    buy_url="https://www.google.at/search?tbm=shop&q=Hape+E0403",
)
assert search_only.buy_url == ""
assert search_only.url == ""
print("URL_NORMALIZACE_OK", item.buy_url)

# 4. Pořadí karet se srovná bez ohledu na vstup.
report = FinalReport(
    items=[
        card("MODERNÍ TREND / INOVACE", "Kávovar Philips EP5447/90", 599.0, 380.0),
        card("NEJLEPŠÍ CENA / VÝKON", "Kávovar DeLonghi ECAM310.80.SB", 329.0, 210.0),
        card("NEJLEVNĚJŠÍ FUNKČNÍ VOLBA", "Kávovar DeLonghi ECAM290.61.SB", 89.0, 45.0),
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
# Strop se neposílá k opravě, i když je nejlevnější kus nad ním.
assert audit_report(report, over_budget) == []
tight = report.model_copy(deep=True)
_stamp_verdict(tight, ScoutRequest(query="kávovar", max_budget=20.0), [])
assert "Audit prošel" in tight.supervisor_verdict
assert "nelze dodržet" in tight.supervisor_verdict
assert "20,00 €" in tight.supervisor_verdict
assert "89,00 €" in tight.supervisor_verdict

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
            "Kávovar DeLonghi ECAM290.61.SB",
            89.0,
            45.0,
            ["Příkon 850 W", "Tlak 20 barů", "Cenově dostupný model za 89 EUR"],
            ["plastové tělo", "bez ohřevu mléka"],
        ),
        card("NEJLEPŠÍ CENA / VÝKON", "Kávovar DeLonghi ECAM310.80.SB", 329.0, 210.0),
        card("MODERNÍ TREND / INOVACE", "Kávovar Philips EP5447/90", 599.0, 380.0),
    ],
    supervisor_verdict="Modely jsou v Rakousku dostupné.",
)
filler_problems = audit_report(price_vata, clean_request)
assert len(filler_problems) == 1, filler_problems
assert "jen opakují cenu" in filler_problems[0], filler_problems
# Kompromis smí cenu zmínit, vyšší cena je legitimní nevýhoda.
assert audit_report(report, clean_request) == []
print("DETEKTOR_CENOVE_VATY_OK")

# 11. Živý úryvek drží cenu. Nákupní URL už není vymyšlená cesta výrobce.
assert extract_prices("heute 1.299,00 € statt 1.499,00 EUR") == [1299.0, 1499.0]
assert extract_prices("EUR 249.90 im Shop") == [249.9]
assert canonical_url("https://www.Shop.AT/p/1/?utm_source=newsletter") == "https://shop.at/p/1"
evidence = MarketEvidence(
    hits=[
        WebHit(
            title="DeLonghi ECAM290.61.SB",
            url=OFFER_URL,
            snippet="249,00 €",
            prices_eur=[249.0],
        )
    ]
)
missing = report.model_copy(deep=True)
missing.items[0].url = "https://www.alternate.de/html/product/delonghi-1"
live_problems = audit_report(missing, ScoutRequest(query="kávovar"), evidence=evidence)
assert not any("není mezi živě nalezenými odkazy" in problem for problem in live_problems), live_problems
assert all(card_item.buy_url == OFFER_URL for card_item in report.items)
only_first = report.model_copy(deep=True)
only_first.items[0].estimated_price_eur = 249.0
only_first.items[1].url = "https://www.amazon.de/dp/B0TESTVALUE01"
only_first.items[2].url = "https://www.jura.com/de/product/e8-123"
broad = MarketEvidence(
    hits=[
        WebHit(title="DeLonghi ECAM290.61.SB MediaMarkt", url=OFFER_URL, snippet="249,00 €", prices_eur=[249.0]),
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

# 12. Nákupní dotaz je jen značka a modelové číslo, plus záporná slova proti dílům.
def shop_query(url: str) -> str:
    return unquote_plus(url.split("q=", 1)[1])

focus = shopping_focus("Kávovar De'Longhi Dedica Style EC 685.M pákový")
assert focus == "De'Longhi EC 685.M", focus
bought = shop_query(buy_url_for("Kávovar De'Longhi Dedica Style EC 685.M pákový"))
assert bought.startswith("De'Longhi EC 685.M "), bought
assert "Dedica" not in bought, bought
assert "pákový" not in bought, bought
for excluded in (
    "-náhradní",
    "-díl",
    "-těsnění",
    "-příslušenství",
    "-ersatzteil",
    "-zubehör",
    "-dichtung",
):
    assert excluded in bought, (excluded, bought)
assert shopping_focus("Hape E0403") == "Hape E0403"
assert "Hape E0403" in shop_query(buy_url_for("Hape E0403"))
assert shopping_focus("Philips HD8651/11 Series 2000 Latte") == "Philips HD8651/11"
print("NAKUPNI_DOTAZ_OK", bought)

# 13. Mlýnek v 7. pádě a výběhový model filtr vyřadí, i když text mlýnek slíbí.
assert requires_grinder("kávovar s mlýnkem")
assert requires_grinder("kavovar s mlynkem")
assert requires_grinder("espresso s Mahlwerk")
assert not requires_grinder("pákový kávovar")
grinder_miss = FinalReport(
    items=[
        card(
            "NEJLEVNĚJŠÍ FUNKČNÍ VOLBA",
            "Kávovar DeLonghi Dedica EC685",
            125.0,
            70.0,
            ["má mlýnek", "tlak 15 barů", "příkon 1350 W"],
            ["plastové tělo", "nádrž 1,1 l"],
        ),
        card("NEJLEPŠÍ CENA / VÝKON", "Kávovar DeLonghi ECAM310.80.SB", 329.0, 210.0),
        card("MODERNÍ TREND / INOVACE", "Kávovar Philips EP5447/90", 599.0, 380.0),
    ],
    supervisor_verdict="Modely jsou v Rakousku dostupné.",
)
grinder_problems = " | ".join(
    audit_report(grinder_miss, ScoutRequest(query="kávovar s mlýnkem"))
)
assert "nesplňuje klíčové slovo mlýnek" in grinder_problems, grinder_problems
assert "diskvalifikovaný" in grinder_problems, grinder_problems
old_model = FinalReport(
    items=[
        card("NEJLEVNĚJŠÍ FUNKČNÍ VOLBA", "Kávovar Philips HD8651", 199.0, 80.0),
        card("NEJLEPŠÍ CENA / VÝKON", "Kávovar DeLonghi ECAM310.80.SB", 329.0, 210.0),
        card("MODERNÍ TREND / INOVACE", "Kávovar Philips EP5447/90", 599.0, 380.0),
    ],
    supervisor_verdict="Modely jsou v Rakousku dostupné.",
)
old_problems = " | ".join(audit_report(old_model, ScoutRequest(query="kávovar")))
assert "starší než 2022 nebo výběhový" in old_problems, old_problems
assert "HD865" in old_problems, old_problems
print("FILTR_MODELU_OK")

# 14. Serper: Rakousko, očištěná cena, přímý odkaz. Bez shody se nic nevymýšlí.
assert "Živé nabídky nebyly nalezeny" in LIVE_OFFERS_MISSING
assert "paměti" in LIVE_OFFERS_MISSING
assert "EP2220" not in LIVE_OFFERS_MISSING

SHOPPING_PAYLOAD = {
    "shopping": [
        {
            "title": "Philips EP2220/10 Kaffeevollautomat",
            "source": "MediaMarkt",
            "link": "https://www.mediamarkt.at/de/product/philips-ep2220-10",
            "price": "249,00 €",
            "delivery": "Auf Lager",
            "offers": "8",
        },
        {
            "title": "Philips EP2220/10 Kaffeevollautomat",
            "source": "Saturn",
            "link": "https://www.saturn.at/de/product/philips-ep2220-10",
            "price": "299,00 €",
            "delivery": "Auf Lager",
        },
        {
            "title": "Philips EP5447/90 LatteGo Kaffeevollautomat",
            "source": "Cyberport",
            "link": "https://www.cyberport.at/philips-ep5447.html",
            "price": "€329.00",
            "delivery": "Lieferung 2-4 Tage",
        },
        {
            "title": "De'Longhi ECAM310.80.SB Magnifica Evo",
            "source": "Amazon",
            "link": "https://www.amazon.de/dp/B0ECAM31080",
            "price": "399,00 €",
            "delivery": "Sofort lieferbar",
        },
        {
            "title": "Philips EP3300/10 Kaffeevollautomat",
            "source": "electronic4you",
            "link": "https://www.electronic4you.at/philips-ep3300",
            "price": "1.099,00 €",
            "delivery": "Auf Lager",
        },
        {
            "title": "De'Longhi Dedica EC685",
            "source": "Amazon",
            "link": "https://www.amazon.de/dp/B0DEDICA123",
            "price": "€129.00",
            "delivery": "Sofort lieferbar",
        },
        {
            "title": "Google obal",
            "source": "Google",
            "link": "https://www.google.at/search?tbm=shop&q=kaffee",
            "price": "99,00 €",
        },
        {
            "title": "USD gadget",
            "source": "US Shop",
            "link": "https://www.shop-example.com/p/1",
            "price": "$50.00",
        },
    ]
}
parsed = parse_serper_shopping(SHOPPING_PAYLOAD)
assert len(parsed) == 6, [(offer.title, offer.price_eur) for offer in parsed]
assert parsed[0].price_eur == 249.0
assert parsed[0].source == "MediaMarkt"
assert parsed[0].availability == "Auf Lager"
assert parsed[0].link.startswith("https://www.mediamarkt.at/")
assert all("google." not in offer.link for offer in parsed)
assert all(offer.price_eur != 50.0 for offer in parsed)

kept = prepare_offers(parsed, ScoutRequest(query="kávovar s mlýnkem", max_budget=400))
assert [offer.price_eur for offer in kept] == [249.0, 329.0, 399.0], [
    (offer.title, offer.price_eur) for offer in kept
]
assert all("dedica" not in offer.title.lower() for offer in kept)
assert kept[0].link.startswith("https://www.mediamarkt.at/")

def picked(offer_id, badge, name):
    return OfferChoice(
        offer_id=offer_id,
        badge=badge,
        name_cz=name,
        pros=["keramický mlýnek s 12 stupni", "tlak čerpadla 15 barů", "nádrž na vodu 1,8 l"],
        cons=["jeden zásobník na zrna", "mléko se pění ručně"],
        verdict_target="Pro domácnost, která chce zrnkový automat.",
        willhaben_used_price_eur=150.0,
        willhaben_liquidity="Vysoká (prodá se do týdne)",
    )

bound, bind_problems = bind_shortlist(
    OfferShortlist(
        choices=[
            picked(1, "NEJLEVNĚJŠÍ FUNKČNÍ VOLBA", "Kávovar Philips EP2220/10"),
            picked(2, "NEJLEPŠÍ CENA / VÝKON", "Kávovar Philips EP5447/90"),
            picked(3, "MODERNÍ TREND / INOVACE", "Kávovar De'Longhi ECAM310.80.SB"),
        ],
        supervisor_verdict="Tři nabídky jsou z rakouského Google Shopping.",
    ),
    kept,
    ScoutRequest(query="kávovar s mlýnkem", max_budget=400),
)
assert bind_problems == [], bind_problems
assert bound is not None
assert [card_item.estimated_price_eur for card_item in bound.items] == [249.0, 329.0, 399.0]
assert [card_item.buy_url for card_item in bound.items] == [offer.link for offer in kept]
assert bound.items[0].offer_origin == "Lokální rakouský e-shop"
assert bound.items[0].ship_from_country == "Rakousko"
assert bound.items[2].offer_origin == "EU sklad"
assert bound.items[2].ship_from_country == "Německo"
assert all("google.at/search" not in card_item.buy_url for card_item in bound.items)
miss, miss_problems = bind_shortlist(
    OfferShortlist(
        choices=[
            picked(9, "NEJLEVNĚJŠÍ FUNKČNÍ VOLBA", "Kávovar Philips EP2220/10"),
            picked(2, "NEJLEPŠÍ CENA / VÝKON", "Kávovar Philips EP5447/90"),
            picked(3, "MODERNÍ TREND / INOVACE", "Kávovar De'Longhi ECAM310.80.SB"),
        ],
        supervisor_verdict="Číslo mimo seznam.",
    ),
    kept,
    ScoutRequest(query="kávovar s mlýnkem", max_budget=400),
)
assert miss is None
assert miss_problems

saved_key = os.environ.pop("SERPER_API_KEY", None)
try:
    try:
        search_serper_shopping("kávovar s mlýnkem")
        raise AssertionError("chybějící klíč měl selhat")
    except SerperShoppingError as exc:
        assert "SERPER_API_KEY" in str(exc)
finally:
    if saved_key is not None:
        os.environ["SERPER_API_KEY"] = saved_key

captured = {}

class _Body:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

def fake_urlopen(request, timeout=0):
    captured["url"] = request.full_url
    captured["body"] = json.loads(request.data.decode("utf-8"))
    captured["key"] = request.get_header("X-api-key")
    captured["timeout"] = timeout
    return _Body(SHOPPING_PAYLOAD)

os.environ["SERPER_API_KEY"] = "test-key"
try:
    downloaded = search_serper_shopping("kávovar s mlýnkem", urlopen=fake_urlopen)
finally:
    if saved_key is None:
        os.environ.pop("SERPER_API_KEY", None)
    else:
        os.environ["SERPER_API_KEY"] = saved_key

assert captured["url"] == "https://google.serper.dev/shopping"
assert captured["body"]["q"] == "kávovar s mlýnkem"
assert captured["body"]["gl"] == "at"
assert captured["body"]["hl"] == "de"
assert captured["key"] == "test-key"
assert len(downloaded) == 6

def broken_open(request, timeout=0):
    raise urllib.error.URLError("serper down")

os.environ["SERPER_API_KEY"] = "test-key"
try:
    try:
        search_serper_shopping("kávovar", urlopen=broken_open)
        raise AssertionError("chyba API měla selhat bez vymyšlených produktů")
    except SerperShoppingError:
        pass
finally:
    if saved_key is None:
        os.environ.pop("SERPER_API_KEY", None)
    else:
        os.environ["SERPER_API_KEY"] = saved_key
print("SERPER_OK", [offer.price_eur for offer in kept])

print("\nALL_DETERMINISTIC_CHECKS_OK")
