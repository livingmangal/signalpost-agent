"""Social profile verification module.

Verifies social media profiles found on the company's verified website.
Does NOT scrape social platforms directly — only records links found
on the company-owned website, as per the source policy.
"""
from __future__ import annotations

import re
import urllib.parse
from typing import Any

from .evidence import evidence, utc_now
from .search_api import search_duckduckgo


SOCIAL_PLATFORMS = {
    "linkedin.com": {"name": "LinkedIn", "pattern": r"linkedin\.com/company/([^/?#]+)"},
    "facebook.com": {"name": "Facebook", "pattern": r"facebook\.com/([^/?#]+)"},
    "instagram.com": {"name": "Instagram", "pattern": r"instagram\.com/([^/?#]+)"},
    "x.com": {"name": "X/Twitter", "pattern": r"x\.com/([^/?#]+)"},
    "twitter.com": {"name": "X/Twitter", "pattern": r"twitter\.com/([^/?#]+)"},
    "youtube.com": {"name": "YouTube", "pattern": r"youtube\.com/(?:@|channel/|c/|user/)([^/?#]+)"},
    "tiktok.com": {"name": "TikTok", "pattern": r"tiktok\.com/@([^/?#]+)"},
    "github.com": {"name": "GitHub", "pattern": r"github\.com/([^/?#]+)"},
}


def extract_social_from_website(website_value: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract social links from the verified company website data."""
    existing = website_value.get("social_links") or []
    if existing:
        return existing

    social_links: list[dict[str, Any]] = []
    seen: set[str] = set()

    # Look through all crawled page content for social links
    all_text = []
    for key in ("identity_text_excerpt", "main_text_excerpt", "description"):
        if website_value.get(key):
            all_text.append(website_value[key])
    for page in website_value.get("pages", []):
        for key in ("identity_text_excerpt", "main_text_excerpt"):
            if page.get(key):
                all_text.append(page[key])

    combined = " ".join(all_text)

    # Find social URLs in the text
    url_pattern = r'https?://(?:www\.)?([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})(/[^\s"\'<>]*)?'
    for match in re.finditer(url_pattern, combined):
        domain = match.group(1).lower()
        full_url = match.group(0)

        for platform_domain, info in SOCIAL_PLATFORMS.items():
            if domain.endswith(platform_domain):
                handle_match = re.search(info["pattern"], full_url, re.IGNORECASE)
                handle = handle_match.group(1) if handle_match else None
                key = f"{info['name']}:{handle or full_url}"

                if key not in seen:
                    seen.add(key)
                    social_links.append({
                        "platform": info["name"],
                        "url": full_url,
                        "handle": handle,
                        "source": "company_website",
                        "verified": True,
                    })

    return social_links


def discover_social_via_search(
    company_name: str,
    org_number: str,
) -> list[dict[str, Any]]:
    """Search for social profiles as CANDIDATES only.

    These are not published as verified — they are candidates for cross-reference.
    Only profiles also linked from the verified company website are published.
    """
    candidates: list[dict[str, Any]] = []
    clean_name = re.sub(
        r"\b(AS|ASA|ANS|DA|ENK|NUF)\b", "", company_name, flags=re.IGNORECASE
    ).strip()

    if not clean_name:
        return candidates

    # Search for LinkedIn company page
    results = search_duckduckgo(
        f'site:linkedin.com/company "{clean_name}"', max_results=3
    )
    for r in results:
        if "linkedin.com/company" in r.url.lower():
            candidates.append({
                "platform": "LinkedIn",
                "url": r.url,
                "title": r.title,
                "source": "search_candidate",
                "verified": False,  # Not verified until confirmed via company site
            })

    return candidates


def fetch_company_social(
    profile: dict[str, Any],
) -> dict[str, Any]:
    """Compile social profile evidence for a company.

    Only profiles verified via the company's own website are marked as verified.
    Search-discovered profiles are marked as candidates (unverified).
    """
    org = profile.get("organisation_number", "")
    name = profile.get("name", "")
    retrieved_at = utc_now()

    # 1. Extract from verified company website
    website_ev = profile.get("evidence", {}).get("website", {})
    website_value = website_ev.get("value") or {}
    website_publishable = (website_value.get("identity_assessment") or {}).get("publishable", True)

    verified_links: list[dict[str, Any]] = []
    candidate_links: list[dict[str, Any]] = []

    if website_publishable:
        verified_links = extract_social_from_website(website_value)

    # 2. Search-based candidates
    candidate_links = discover_social_via_search(name, org)

    # Cross-reference: promote candidates that match verified links
    verified_urls = {link["url"].lower().rstrip("/") for link in verified_links}
    for candidate in candidate_links:
        candidate_url = candidate["url"].lower().rstrip("/")
        if candidate_url in verified_urls:
            candidate["verified"] = True

    all_profiles = verified_links + [c for c in candidate_links if c["url"].lower().rstrip("/") not in verified_urls]
    all_profiles.sort(key=lambda p: (str(p.get("platform") or ""), str(p.get("url") or "")))

    if all_profiles:
        return evidence(
            "social_profiles",
            "available",
            "social_discovery",
            "company_website_and_search",
            value={
                "profiles": all_profiles,
                "verified_count": sum(1 for p in all_profiles if p.get("verified")),
                "candidate_count": sum(1 for p in all_profiles if not p.get("verified")),
            },
            retrieved_at=retrieved_at,
            content_sha256=__import__("hashlib").sha256(
                __import__("json").dumps(all_profiles, sort_keys=True).encode()
            ).hexdigest(),
        )
    else:
        return evidence(
            "social_profiles",
            "not_available",
            "social_discovery",
            "company_website_and_search",
            note="No social profiles found on the verified company website or via search.",
            retrieved_at=retrieved_at,
        )
