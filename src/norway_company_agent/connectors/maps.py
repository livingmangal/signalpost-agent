"""Google Maps candidate normalization and scoring against registered entities."""
from __future__ import annotations

import difflib
import math
import re
import urllib.parse

LEGAL_STOP = {
    "as", "asa", "sa", "enk", "nuf", "da", "ans", "ba", "stiftelsen", "sameiet",
    "avd", "avdeling",
}
GENERIC_MAP_TOKENS = {"holding", "eiendom", "invest", "bolig", "service", "drift", "gruppen", "group"}
VERIFIED_TRADE_NAMES = {
    ("932083108", "privatmegleren premium"): "https://www.proff.no/selskap/privatmegleren-premium/oslo/eiendomsmegling/IFEXRXG00B1",
    ("963430663", "mobit kanalveien"): "https://www.mobit.no/forhandlere/bergen/kanalveien",
    ("967292907", "lunsj service og orebekk fisk vilt"): "https://www.starina.no/",
}


def tokens(value: object) -> list[str]:
    normalized = str(value or "").casefold()
    normalized = normalized.translate(str.maketrans({"æ": "ae", "ø": "o", "å": "a"}))
    return re.findall(r"[a-z0-9]+", normalized)


def meaningful_name_tokens(value: object) -> list[str]:
    return [token for token in tokens(value) if token not in LEGAL_STOP and (len(token) >= 3 or token.isdigit())]


def normalized_phone(value: object) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    if digits.startswith("47") and len(digits) > 8:
        digits = digits[2:]
    return digits[-8:]


def registered_domain(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    host = (urllib.parse.urlparse(raw).hostname or "").casefold().removeprefix("www.")
    return host


def review_label(rating: int | float) -> str:
    if rating <= 2:
        return "negative"
    if rating >= 4:
        return "positive"
    return "neutral"


def candidate_score(profile: dict, candidate: dict) -> dict:
    registry = ((profile.get("evidence") or {}).get("registry") or {}).get("value") or {}
    target = set(meaningful_name_tokens(profile.get("name")))
    title = set(meaningful_name_tokens(candidate.get("title")))
    overlap = len(target & title)
    name_score = overlap / len(target) if target else 0.0
    if target and target.issubset(title):
        name_score = 1.0

    registry_street = set(tokens(registry.get("forretningsadresse.adresse")))
    candidate_address = set(tokens(candidate.get("address")))
    postcode = str(registry.get("forretningsadresse.postnummer") or "")
    registry_city = set(tokens(registry.get("forretningsadresse.poststed")))
    address_match = bool(
        registry_street
        and registry_street.issubset(candidate_address)
        and (not postcode or postcode in candidate_address)
    )
    postcode_city_match = bool(
        postcode and postcode in candidate_address
        and (not registry_city or registry_city.issubset(candidate_address))
    )
    registry_phone = normalized_phone(registry.get("telefon") or registry.get("mobil"))
    candidate_phone = normalized_phone(candidate.get("phone"))
    phone_match = bool(len(registry_phone) >= 5 and registry_phone == candidate_phone)

    website = ((profile.get("evidence") or {}).get("website") or {}).get("value") or {}
    identity = website.get("identity_assessment") or {}
    exact_site = website.get("final_url") if identity.get("publishable") else ""
    if not exact_site and identity.get("publishable"):
        exact_site = ((profile.get("evidence") or {}).get("website") or {}).get("source_url")
    expected_domain = registered_domain(exact_site)
    candidate_domain = registered_domain(candidate.get("web_site"))
    website_match = bool(
        expected_domain and candidate_domain
        and (candidate_domain == expected_domain or candidate_domain.endswith("." + expected_domain))
    )
    target_name = " ".join(meaningful_name_tokens(profile.get("name")))
    candidate_name = " ".join(meaningful_name_tokens(candidate.get("title")))
    fuzzy_name_score = difflib.SequenceMatcher(None, target_name, candidate_name).ratio() if target_name and candidate_name else 0.0
    strong_channels = sum((address_match or postcode_city_match, phone_match, website_match))
    accepted = bool((name_score >= 0.99 and strong_channels >= 1) or (name_score >= 0.66 and strong_channels >= 2))
    trade_key = (str(profile.get("organisation_number") or ""), " ".join(tokens(candidate.get("title"))))
    trade_name_source = VERIFIED_TRADE_NAMES.get(trade_key)
    # Shared group addresses and phone numbers are not enough: every trading
    # name must be independently corroborated to the exact organisation.
    trade_name_match = bool(name_score == 0 and address_match and phone_match and trade_name_source)
    verified_domain_fuzzy_name_match = bool(website_match and fuzzy_name_score >= 0.85)
    accepted = accepted or trade_name_match or verified_domain_fuzzy_name_match
    weak_generic_name = len(target) == 1 and next(iter(target), "") in GENERIC_MAP_TOKENS
    if weak_generic_name and not (address_match or phone_match or website_match):
        accepted = False
    score = name_score * 4 + address_match * 3 + phone_match * 2 + website_match * 3
    score += postcode_city_match * 2
    score += min(1.0, math.log10(max(1, int(candidate.get("review_count") or 0))) / 5)
    return {
        "accepted": accepted,
        "score": round(score, 4),
        "name_score": round(name_score, 4),
        "address_match": address_match,
        "postcode_city_match": postcode_city_match,
        "weak_generic_name": weak_generic_name,
        "phone_match": phone_match,
        "website_match": website_match,
        "trade_name_match": trade_name_match,
        "trade_name_source": trade_name_source,
        "verified_domain_fuzzy_name_match": verified_domain_fuzzy_name_match,
        "fuzzy_name_score": round(fuzzy_name_score, 4),
        "target_name_tokens": sorted(target),
        "candidate_name_tokens": sorted(title),
    }
