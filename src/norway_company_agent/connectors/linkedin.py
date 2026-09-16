"""LinkedIn profile, jobs, and candidate discovery normalizers."""
from __future__ import annotations

import html
import json
import re
from urllib.parse import quote, unquote, urlparse
from bs4 import BeautifulSoup


LEGAL_SUFFIXES = {"as", "asa", "ba", "da", "enk", "nuf", "sa", "stiftelsen"}


def clean_number(value: str) -> int | None:
    digits = re.sub(r"\D", "", str(value or ""))
    return int(digits) if digits else None


def normalized_company(value: str) -> str:
    words = re.findall(r"[a-z0-9æøå]+", unquote(str(value or "")).casefold())
    while words and words[-1] in LEGAL_SUFFIXES:
        words.pop()
    return " ".join(words)


def normalized_full_name(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9æøå]+", str(value or "").casefold()))


def canonical_company_url(value: str) -> str | None:
    parsed = urlparse(str(value or "").strip())
    host = (parsed.hostname or "").casefold()
    if host != "linkedin.com" and not host.endswith(".linkedin.com"):
        return None
    parts = [unquote(item).strip() for item in parsed.path.split("/") if item.strip()]
    if len(parts) < 2 or parts[0].casefold() != "company":
        return None
    slug = parts[1].casefold()
    if not slug:
        return None
    return f"https://linkedin.com/company/{quote(slug, safe='-_.~')}"


def legal_name_profile_url(value: str) -> str | None:
    """Build one deterministic stale-handle fallback from the registry legal name."""
    transliterated = (
        str(value or "").casefold().replace("æ", "ae").replace("ø", "o").replace("å", "a")
    )
    words = re.findall(r"[a-z0-9]+", transliterated)
    return f"https://www.linkedin.com/company/{'-'.join(words)}" if words else None


def registered_domain(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlparse(str(value) if "://" in str(value) else f"https://{value}")
    host = (parsed.hostname or "").casefold().removeprefix("www.")
    return host or None


def parse_job_cards(raw: bytes, expected_company_url: str) -> tuple[list[dict], int]:
    soup = BeautifulSoup(raw, "html.parser")
    cards = soup.select("div.base-search-card")
    exact = []
    for card in cards:
        company_link = card.select_one("h4.base-search-card__subtitle a")
        company_url = canonical_company_url(company_link.get("href", "") if company_link else "")
        if company_url != expected_company_url:
            continue
        job_link = card.select_one("a.base-card__full-link")
        job_url = str(job_link.get("href") or "") if job_link else ""
        urn = str(card.get("data-entity-urn") or "")
        job_id_match = re.search(r"(\d{6,})", urn) or re.search(r"-(\d{6,})(?:[/?]|$)", job_url)
        if not job_id_match:
            continue
        job_id = job_id_match.group(1)
        title = card.select_one("span.sr-only")
        company = company_link.get_text(" ", strip=True) if company_link else ""
        location = card.select_one("span.job-search-card__location")
        posted = card.select_one("time")
        exact.append(
            {
                "job_id": job_id,
                "job_url": f"https://www.linkedin.com/jobs/view/{job_id}",
                "title": title.get_text(" ", strip=True) if title else "",
                "company": company,
                "company_url": company_url,
                "location": location.get_text(" ", strip=True) if location else "",
                "date_posted": str(posted.get("datetime") or "") if posted else "",
            }
        )
    return exact, len(cards)


def parse_typeahead(raw: bytes, legal_name: str) -> list[dict]:
    payload = json.loads(raw.decode("utf-8", errors="replace"))
    legal_core = normalized_company(legal_name)
    return [
        {
            "linkedin_company_id": str(item.get("id") or ""),
            "display_name": str(item.get("displayName") or ""),
            "exact_legal_name_core": normalized_company(item.get("displayName")) == legal_core,
        }
        for item in payload
        if item.get("type") == "COMPANY" and item.get("id")
    ]


def parse_exact_typeahead(raw: bytes, legal_name: str) -> list[dict]:
    payload = json.loads(raw.decode("utf-8", errors="replace"))
    expected = normalized_full_name(legal_name)
    return [
        {"linkedin_company_id": str(item["id"]), "display_name": str(item.get("displayName") or "")}
        for item in payload
        if item.get("type") == "COMPANY"
        and item.get("id")
        and normalized_full_name(item.get("displayName")) == expected
    ]


def parse_detail_company_urls(raw: bytes) -> set[str]:
    soup = BeautifulSoup(raw, "html.parser")
    return {
        canonical
        for link in soup.select('a[href*="linkedin.com/company/"]')
        if (canonical := canonical_company_url(str(link.get("href") or "")))
    }


def _json_ld_graph(soup: BeautifulSoup) -> list[dict]:
    rows: list[dict] = []
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            value = json.loads(script.get_text())
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(value, dict) and isinstance(value.get("@graph"), list):
            rows.extend(item for item in value["@graph"] if isinstance(item, dict))
        elif isinstance(value, list):
            rows.extend(item for item in value if isinstance(item, dict))
        elif isinstance(value, dict):
            rows.append(value)
    return rows


def _page_company_ids(soup: BeautifulSoup) -> list[str]:
    encoded_values = set(
        re.findall(r"facetCurrentCompany(?:%3D|=)(?:%255B|%5B|\[)(.*?)(?:%255D|%5D|\])", str(soup), re.I)
    )
    output = set()
    for encoded in encoded_values:
        decoded = unquote(unquote(encoded))
        output.update(re.findall(r"\d+", decoded))
    return sorted(output, key=int)


def _followers(soup: BeautifulSoup) -> int | None:
    descriptions = [
        str(tag.get("content") or "")
        for tag in soup.select('meta[name="description"],meta[property="og:description"],meta[name="twitter:description"]')
    ]
    match = re.search(
        r"([\d\s\u00a0.,]+)\s+(?:followers|follower|følgere|Follower:innen|seguidores)",
        " ".join(descriptions),
        re.I,
    )
    return clean_number(match.group(1)) if match else None


def _about_value(soup: BeautifulSoup, test_id: str) -> str | None:
    node = soup.select_one(f'[data-test-id="{test_id}"]')
    if not node:
        return None
    values = [item.get_text(" ", strip=True) for item in node.select("dd")]
    text = " ".join(values).strip() if values else node.get_text(" ", strip=True)
    return text or None


def _about_website(soup: BeautifulSoup) -> str | None:
    node = soup.select_one('[data-test-id="about-us__website"] dd a')
    if not node:
        return None
    return node.get_text(" ", strip=True) or None


def _post_engagement(soup: BeautifulSoup) -> dict[str, dict[str, int]]:
    result = {}
    for article in soup.select("article.main-feed-activity-card[data-activity-urn]"):
        activity_id = str(article.get("data-activity-urn") or "").split(":")[-1]
        reactions = article.select_one('[data-test-id="social-actions__reactions"]')
        comments = article.select_one('[data-test-id="social-actions__comments"]')
        result[activity_id] = {
            "likes": int(reactions.get("data-num-reactions") or 0) if reactions else 0,
            "comments": int(comments.get("data-num-comments") or 0) if comments else 0,
        }
    return result


def extract_profile(raw: bytes, expected_url: str | None = None) -> dict:
    soup = BeautifulSoup(raw, "html.parser")
    graph = _json_ld_graph(soup)
    organisations = [item for item in graph if item.get("@type") == "Organization"]
    if not organisations:
        raise RuntimeError("LinkedIn guest page returned no structured organization profile")
    organisation = organisations[-1]
    page_url = canonical_company_url(str(organisation.get("url") or ""))
    if expected_url and page_url != expected_url:
        raise RuntimeError(f"LinkedIn page identity mismatch: expected {expected_url}, received {page_url}")
    number = organisation.get("numberOfEmployees") or {}
    visible_employees = clean_number(number.get("value")) if isinstance(number, dict) else None
    engagement = _post_engagement(soup)
    posts = []
    for item in graph:
        if item.get("@type") != "DiscussionForumPosting":
            continue
        author_url = canonical_company_url(str((item.get("author") or {}).get("url") or ""))
        if page_url and author_url != page_url:
            continue
        url = str(item.get("url") or item.get("mainEntityOfPage") or "")
        activity_match = re.search(r"activity-(\d+)", unquote(url))
        metrics = engagement.get(activity_match.group(1) if activity_match else "", {"likes": 0, "comments": 0})
        posts.append(
            {
                "url": url,
                "date_published": item.get("datePublished"),
                "text": str(item.get("text") or "").strip(),
                **metrics,
            }
        )
    return {
        "name": str(organisation.get("name") or ""),
        "page_url": page_url,
        "linkedin_organisation_ids": _page_company_ids(soup),
        "followers": _followers(soup),
        "visible_employees": visible_employees,
        "employee_size_label": _about_value(soup, "about-us__size"),
        "description": str(organisation.get("description") or ""),
        "website": html.unescape(_about_website(soup) or "") or None,
        "industry": _about_value(soup, "about-us__industry"),
        "headquarters": _about_value(soup, "about-us__headquarters"),
        "address": organisation.get("address"),
        "posts": posts,
    }


def assess_profile_identity(profile: dict, requested_url: str | None, metrics: dict) -> dict:
    website = ((profile.get("evidence") or {}).get("website") or {})
    website_value = website.get("value") or {}
    official_domain = registered_domain(
        website_value.get("final_url") or website.get("source_url") or profile.get("website")
    )
    linkedin_domain = registered_domain(metrics.get("website"))
    legal_core = normalized_company(str(profile.get("name") or ""))
    linkedin_core = normalized_company(str(metrics.get("name") or ""))
    exact_name = bool(legal_core and legal_core == linkedin_core)
    reverse_domain = bool(official_domain and official_domain == linkedin_domain)
    structured_page = bool(metrics.get("page_url"))
    return {
        "publishable_candidate": bool(structured_page and (exact_name or reverse_domain)),
        "requested_url": requested_url,
        "resolved_url": metrics.get("page_url"),
        "exact_legal_name_core": exact_name,
        "official_domain": official_domain,
        "linkedin_website_domain": linkedin_domain,
        "reverse_domain_match": reverse_domain,
        "method": "company_site_crosslink_plus_linkedin_name_or_reverse_domain_v1",
    }


def official_site_aliases(profile: dict) -> list[str]:
    website = (profile.get("evidence") or {}).get("website") or {}
    if website.get("status") != "available":
        return []
    value = website.get("value") or {}
    raw = [value.get("title")]
    raw.extend(item.get("name") for item in value.get("structured_organisations") or [] if isinstance(item, dict))
    aliases = []
    banned = {"home", "homepage", "forside", "welcome", "velkommen", "official site"}
    legal = normalized_full_name(profile.get("name"))
    for item in raw:
        candidate = re.split(r"\s+[|\u2013\u2014]\s+", str(item or ""), maxsplit=1)[0].strip()
        normalized = normalized_full_name(candidate)
        if not normalized or normalized in banned or normalized == legal or len(normalized) < 3 or len(normalized) > 80:
            continue
        if candidate not in aliases:
            aliases.append(candidate)
    return aliases[:3]


def profile_leaders(profile: dict) -> list[str]:
    roles = (((profile.get("evidence") or {}).get("roles") or {}).get("value") or {}).get("roles") or []
    priority = {"DAGL", "LEDE", "INNH"}
    return [str(item.get("name") or "") for item in roles if item.get("role_code") in priority and item.get("name")][:5]


def discovery_identity(profile: dict, linkedin_profile: dict, sources: set[str]) -> dict:
    legal_full = normalized_full_name(profile.get("name"))
    linkedin_full = normalized_full_name(linkedin_profile.get("name"))
    full_name_match = bool(legal_full and legal_full == linkedin_full)
    core_name_match = bool(
        normalized_company(profile.get("name"))
        and normalized_company(profile.get("name")) == normalized_company(linkedin_profile.get("name"))
    )
    website = (profile.get("evidence") or {}).get("website") or {}
    value = website.get("value") or {}
    official_domain = registered_domain(value.get("final_url") or profile.get("website"))
    linkedin_domain = registered_domain(linkedin_profile.get("website"))
    domain_match = bool(official_domain and linkedin_domain and official_domain == linkedin_domain)
    municipality = normalized_full_name(profile.get("municipality"))
    linkedin_location = normalized_full_name(
        " ".join(
            str(item or "")
            for item in (
                linkedin_profile.get("headquarters"),
                json.dumps(linkedin_profile.get("address") or {}, ensure_ascii=False),
            )
        )
    )
    location_match = bool(municipality and municipality in linkedin_location)
    company_id_job_link = "company_id_job_link" in sources
    aliases = [item.split(":", 1)[1] for item in sources if item.startswith("official_site_alias:")]
    linkedin_name = normalized_full_name(linkedin_profile.get("name"))
    alias_match = any(
        normalized_full_name(alias) == linkedin_name
        or normalized_company(alias) == normalized_company(linkedin_profile.get("name"))
        for alias in aliases
    )
    linkedin_text = normalized_full_name(
        " ".join(
            [str(linkedin_profile.get("description") or "")]
            + [str(item.get("text") or "") for item in linkedin_profile.get("posts") or []]
        )
    )
    matched_leaders = [leader for leader in profile_leaders(profile) if normalized_full_name(leader) in linkedin_text]
    exact = bool(
        (core_name_match and domain_match)
        or (alias_match and domain_match)
        or (full_name_match and location_match)
        or (full_name_match and company_id_job_link)
        or (alias_match and location_match and matched_leaders)
    )
    return {
        "exact_entity": exact,
        "full_legal_name_match": full_name_match,
        "legal_name_core_match": core_name_match,
        "official_domain": official_domain,
        "linkedin_website_domain": linkedin_domain,
        "reverse_domain_match": domain_match,
        "municipality": profile.get("municipality"),
        "linkedin_headquarters": linkedin_profile.get("headquarters"),
        "location_match": location_match,
        "company_id_job_link": company_id_job_link,
        "official_site_aliases": aliases,
        "official_site_alias_match": alias_match,
        "matched_registered_leaders": matched_leaders,
        "method": "linkedin_typeahead_plus_domain_location_or_company_id_job_v1",
    }
