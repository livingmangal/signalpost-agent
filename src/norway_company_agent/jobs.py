"""Job discovery from permitted public sources.

Discovers job postings from:
1. Company career pages (already crawled by website module)
2. Finn.no job listings via search
3. Arbeidsplassen.nav.no via search
"""
from __future__ import annotations

import re
import urllib.parse
from typing import Any

from .evidence import evidence, utc_now
from .search_api import search_duckduckgo, SearchResult


def extract_jobs_from_career_page(page_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract job postings from a company's career/jobs page content."""
    jobs: list[dict[str, Any]] = []
    text = page_data.get("main_text_excerpt", "") or ""
    title = page_data.get("title", "") or ""
    url = page_data.get("url", "") or ""

    # Look for job-like patterns in the text
    job_patterns = [
        r"(?i)(senior|junior|lead|head of|manager|engineer|developer|designer|"
        r"analyst|consultant|advisor|coordinator|director|specialist|"
        r"rådgiver|konsulent|ingeniør|utvikler|leder|sjef)"
        r"[^.!\n]{0,80}",
    ]

    found_titles: set[str] = set()
    for pattern in job_patterns:
        for match in re.finditer(pattern, text):
            job_title = match.group(0).strip()
            # Clean up the job title
            job_title = re.sub(r"\s+", " ", job_title)[:120]
            if len(job_title) > 10 and job_title.lower() not in found_titles:
                found_titles.add(job_title.lower())
                jobs.append({
                    "title": job_title,
                    "source_url": url,
                    "source_type": "company_career_page",
                })

    return jobs[:10]  # Limit to 10 per page


def fetch_nav_arbeidsplassen_jobs(
    company_name: str,
    org_number: str,
) -> list[dict[str, Any]]:
    """Fetch official open job postings directly from NAV Arbeidsplassen API."""
    jobs: list[dict[str, Any]] = []
    clean_name = re.sub(
        r"\b(AS|ASA|ANS|DA|ENK|NUF)\b", "", company_name, flags=re.IGNORECASE
    ).strip()

    if not clean_name:
        return jobs

    import httpx
    url = "https://arbeidsplassen.nav.no/stillinger/api/search"
    target_tokens = set(re.findall(r"\w+", clean_name.casefold()))

    try:
        response = httpx.get(
            url,
            params={"q": f'"{clean_name}"'},
            headers={"User-Agent": "BuilderrAgent/1.0 (NLOD-open-data)"},
            timeout=4.0,
        )
        if response.status_code == 200:
            data = response.json()
            hits = data.get("hits", {}).get("hits", [])
            for hit in hits[:10]:
                source = hit.get("_source", {})
                employer = source.get("employer", {})
                emp_name = str(employer.get("name", "")).casefold()
                emp_tokens = set(re.findall(r"\w+", emp_name))
                
                # Check identity gate: employer name overlap or org match
                if target_tokens and (target_tokens.issubset(emp_tokens) or len(target_tokens & emp_tokens) >= max(1, len(target_tokens) - 1)):
                    uuid = source.get("uuid")
                    title = source.get("title")
                    locations = source.get("locationList") or []
                    loc_str = locations[0].get("city") if locations else None
                    if title and uuid:
                        jobs.append({
                            "title": title,
                            "url": f"https://arbeidsplassen.nav.no/stillinger/stilling/{uuid}",
                            "location": loc_str,
                            "published": source.get("published"),
                            "platform": "arbeidsplassen.nav.no",
                            "source_type": "official_job_registry",
                        })
    except Exception:
        pass

    return jobs


def discover_jobs_via_search(
    company_name: str,
    org_number: str,
) -> list[dict[str, Any]]:
    """Search for job postings on permitted Norwegian job platforms."""
    jobs: list[dict[str, Any]] = []
    clean_name = re.sub(
        r"\b(AS|ASA|ANS|DA|ENK|NUF)\b", "", company_name, flags=re.IGNORECASE
    ).strip()

    if not clean_name:
        return jobs

    # 1. Official NAV Arbeidsplassen API
    nav_api_jobs = fetch_nav_arbeidsplassen_jobs(company_name, org_number)
    jobs.extend(nav_api_jobs)

    # 2. Search Finn.no jobs if we don't have enough postings yet
    if len(jobs) < 5:
        finn_results = search_duckduckgo(
            f'site:finn.no/job "{clean_name}"', max_results=5
        )
        for r in finn_results:
            if "finn.no" in r.url.lower() and "/job" in r.url.lower():
                jobs.append({
                    "title": r.title,
                    "url": r.url,
                    "snippet": r.snippet,
                    "platform": "finn.no",
                    "source_type": "job_platform_search",
                })

    # 3. Search Arbeidsplassen via search if API was empty
    if not nav_api_jobs and len(jobs) < 5:
        nav_results = search_duckduckgo(
            f'site:arbeidsplassen.nav.no "{clean_name}"', max_results=5
        )
        for r in nav_results:
            if "arbeidsplassen" in r.url.lower() or "nav.no" in r.url.lower():
                jobs.append({
                    "title": r.title,
                    "url": r.url,
                    "snippet": r.snippet,
                    "platform": "arbeidsplassen.nav.no",
                    "source_type": "job_platform_search",
                })

    return jobs


def fetch_company_jobs(
    profile: dict[str, Any],
) -> dict[str, Any]:
    """Fetch all discoverable jobs for a company.

    Combines career page extraction with search-based discovery.
    Returns an evidence record.
    """
    org = profile.get("organisation_number", "")
    name = profile.get("name", "")
    retrieved_at = utc_now()

    all_jobs: list[dict[str, Any]] = []

    # 1. Extract from career pages if website was crawled
    website_ev = profile.get("evidence", {}).get("website", {})
    website_value = website_ev.get("value") or {}
    for page in website_value.get("pages", []):
        page_url = (page.get("url") or "").lower()
        if any(kw in page_url for kw in ("career", "job", "stilling", "ledig")):
            career_jobs = extract_jobs_from_career_page(page)
            all_jobs.extend(career_jobs)

    # 2. Search job platforms
    search_jobs = discover_jobs_via_search(name, org)
    all_jobs.extend(search_jobs)

    if all_jobs:
        return evidence(
            "jobs",
            "available",
            "job_discovery",
            "multiple_sources",
            value={
                "postings": all_jobs,
                "count": len(all_jobs),
                "sources": list({j.get("platform") or j.get("source_type", "unknown") for j in all_jobs}),
            },
            retrieved_at=retrieved_at,
            content_sha256=__import__("hashlib").sha256(
                __import__("json").dumps(all_jobs, sort_keys=True).encode()
            ).hexdigest(),
        )
    else:
        return evidence(
            "jobs",
            "not_available",
            "job_discovery",
            "multiple_sources",
            note="No current job postings found on permitted platforms.",
            retrieved_at=retrieved_at,
        )
