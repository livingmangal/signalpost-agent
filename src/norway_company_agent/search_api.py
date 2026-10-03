"""Search API clients for company discovery.

Integrates multiple free-tier and open search providers:
- Brave Search API (free tier: 2,000 queries/month, key optional)
- Tavily Search API (free tier: 1,000 queries/month, key optional)
- SerpAPI (free tier: 100 queries/month, key optional)
- DuckDuckGo (free, no key)
- Norwegian Wikipedia API (free, open data, no key)
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from .evidence import evidence, utc_now


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    source: str  # "duckduckgo", "brave", "tavily", "serpapi", "wikipedia"


@dataclass
class SearchBudget:
    max_queries: int = 1000
    queries_used: int = 0
    max_brave_queries: int = 2000
    max_tavily_queries: int = 1000
    max_serpapi_queries: int = 100
    brave_used: int = 0
    tavily_used: int = 0
    serpapi_used: int = 0

    @property
    def remaining(self) -> int:
        return self.max_queries - self.queries_used

    @property
    def exhausted(self) -> bool:
        return self.queries_used >= self.max_queries


_search_budget = SearchBudget()


def get_search_budget() -> SearchBudget:
    return _search_budget


def reset_search_budget(max_queries: int = 1000) -> None:
    global _search_budget
    _search_budget = SearchBudget(max_queries=max_queries)


def search_duckduckgo(query: str, max_results: int = 8) -> list[SearchResult]:
    """Search using DuckDuckGo (no API key needed)."""
    budget = get_search_budget()
    if budget.exhausted:
        return []
    budget.queries_used += 1
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            raw = list(ddgs.text(query, max_results=max_results))
        return [
            SearchResult(
                title=r.get("title", ""),
                url=r.get("href", ""),
                snippet=r.get("body", ""),
                source="duckduckgo",
            )
            for r in raw
        ]
    except Exception:
        return []


def _get_api_keys(env_var: str) -> list[str]:
    raw = os.environ.get(env_var, "").strip()
    return [k.strip() for k in raw.split(",") if k.strip()]


def search_brave(query: str, max_results: int = 8) -> list[SearchResult]:
    """Search using Brave Search API (supports single key or comma-separated pool)."""
    keys = _get_api_keys("BRAVE_API_KEY")
    if not keys:
        return []
    budget = get_search_budget()
    if budget.brave_used >= budget.max_brave_queries:
        return []
    budget.queries_used += 1
    budget.brave_used += 1

    for api_key in keys:
        try:
            url = f"https://api.search.brave.com/res/v1/web/search?q={urllib.parse.quote(query)}&count={max_results}"
            req = urllib.request.Request(url, headers={
                "Accept": "application/json",
                "X-Subscription-Token": api_key,
                "User-Agent": "BuilderrAgent/1.0",
            })
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            results = data.get("web", {}).get("results", [])
            return [
                SearchResult(
                    title=r.get("title", ""),
                    url=r.get("url", ""),
                    snippet=r.get("description", ""),
                    source="brave",
                )
                for r in results[:max_results]
            ]
        except urllib.error.HTTPError as exc:
            if exc.code in {429, 403}:
                continue
        except Exception:
            continue
    return []


def search_tavily(query: str, max_results: int = 5) -> list[SearchResult]:
    """Search using Tavily Search API (supports single key or comma-separated pool)."""
    keys = _get_api_keys("TAVILY_API_KEY")
    if not keys:
        return []
    budget = get_search_budget()
    if budget.tavily_used >= budget.max_tavily_queries:
        return []
    budget.queries_used += 1
    budget.tavily_used += 1

    for api_key in keys:
        try:
            url = "https://api.tavily.com/search"
            payload = json.dumps({
                "api_key": api_key,
                "query": query,
                "search_depth": "basic",
                "max_results": max_results,
            }).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json", "User-Agent": "BuilderrAgent/1.0"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            results = data.get("results", [])
            return [
                SearchResult(
                    title=r.get("title", ""),
                    url=r.get("url", ""),
                    snippet=r.get("content", ""),
                    source="tavily",
                )
                for r in results[:max_results]
            ]
        except urllib.error.HTTPError as exc:
            if exc.code in {429, 403}:
                continue
        except Exception:
            continue
    return []


def search_serpapi(query: str, max_results: int = 5) -> list[SearchResult]:
    """Search using SerpAPI (free tier: 100 queries/month)."""
    api_key = os.environ.get("SERPAPI_API_KEY", "").strip()
    if not api_key:
        return []
    budget = get_search_budget()
    if budget.serpapi_used >= budget.max_serpapi_queries:
        return []
    budget.queries_used += 1
    budget.serpapi_used += 1
    try:
        url = f"https://serpapi.com/search.json?q={urllib.parse.quote(query)}&num={max_results}&api_key={api_key}"
        req = urllib.request.Request(url, headers={"User-Agent": "BuilderrAgent/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        results = data.get("organic_results", [])
        return [
            SearchResult(
                title=r.get("title", ""),
                url=r.get("link", ""),
                snippet=r.get("snippet", ""),
                source="serpapi",
            )
            for r in results[:max_results]
        ]
    except Exception:
        return []


def search_wikipedia_norway(query: str, max_results: int = 3) -> list[SearchResult]:
    """Search Norwegian Wikipedia for verified corporate background (100% free open API)."""
    clean_query = re.sub(r"\b(AS|ASA|ANS|DA|ENK|NUF)\b", "", query, flags=re.IGNORECASE).strip()
    if not clean_query or len(clean_query) < 3:
        return []
    try:
        url = (
            f"https://no.wikipedia.org/w/api.php?action=query&list=search&srsearch="
            f"{urllib.parse.quote(clean_query)}&format=json"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "BuilderrAgent/1.0 (https://builderr.ai)"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        items = data.get("query", {}).get("search", [])
        results: list[SearchResult] = []
        for it in items[:max_results]:
            title = it.get("title", "")
            page_url = f"https://no.wikipedia.org/wiki/{urllib.parse.quote(title)}"
            # Strip html tags from snippet
            snippet = re.sub(r"<[^>]+>", "", it.get("snippet", ""))
            results.append(SearchResult(
                title=title,
                url=page_url,
                snippet=snippet,
                source="wikipedia",
            ))
        return results
    except Exception:
        return []


def search_company(
    company_name: str,
    org_number: str,
    *,
    include_site_queries: bool = True,
) -> list[SearchResult]:
    """Multi-provider cascade search for a company.

    Prioritizes free API keys if configured (Brave, Tavily, SerpAPI),
    falls back to open services (Wikipedia, DuckDuckGo).
    """
    all_results: list[SearchResult] = []
    seen_urls: set[str] = set()

    def _add(results: list[SearchResult]) -> None:
        for r in results:
            normalized = r.url.rstrip("/").lower()
            if normalized and normalized not in seen_urls:
                seen_urls.add(normalized)
                all_results.append(r)

    clean_name = re.sub(r"\b(AS|ASA|ANS|DA|ENK|NUF)\b", "", company_name, flags=re.IGNORECASE).strip()

    # 1. Try Brave Search API if key provided (best coverage)
    if os.environ.get("BRAVE_API_KEY"):
        _add(search_brave(f'"{company_name}" {org_number}', max_results=5))
        if clean_name:
            _add(search_brave(f'"{clean_name}" Norway', max_results=4))
        if include_site_queries and clean_name:
            _add(search_brave(f'site:finn.no "{clean_name}"', max_results=3))

    # 2. Try Tavily Search API if key provided
    if os.environ.get("TAVILY_API_KEY") and len(all_results) < 3:
        _add(search_tavily(f'"{company_name}" Norway {org_number}', max_results=4))
        if include_site_queries and clean_name:
            _add(search_tavily(f'"{clean_name}" site:finn.no/job', max_results=3))

    # 3. Try SerpAPI if key provided
    if os.environ.get("SERPAPI_API_KEY") and len(all_results) < 3:
        _add(search_serpapi(f'"{company_name}" {org_number}', max_results=4))

    # 4. Try DuckDuckGo
    if len(all_results) < 2:
        _add(search_duckduckgo(f'"{company_name}" {org_number}', max_results=5))
        if clean_name:
            _add(search_duckduckgo(f'"{clean_name}" Norway', max_results=4))

    # 5. Open Wikipedia Search (100% free, reliable supplementary facts)
    if clean_name:
        _add(search_wikipedia_norway(clean_name, max_results=2))

    return all_results


def discover_website_candidates(
    company_name: str,
    org_number: str,
    registry_website: str | None = None,
) -> list[dict[str, Any]]:
    """Find candidate website URLs for a company.

    Returns ranked list of candidate URLs with confidence signals.
    """
    import tldextract

    candidates: dict[str, dict[str, Any]] = {}

    # If registry has a website, it's the top authoritative candidate - return immediately to save quota
    if registry_website and registry_website.strip():
        reg_clean = registry_website.strip()
        url = reg_clean if "://" in reg_clean else f"https://{reg_clean}"
        norm_key = url.rstrip("/").lower()
        candidates[norm_key] = {
            "url": url,
            "source": "official_registry",
            "confidence": 0.95,
            "signals": ["registry_listed"],
        }
        return [candidates[norm_key]]

    results = search_company(company_name, org_number, include_site_queries=False)

    for r in results:
        try:
            parsed = urllib.parse.urlparse(r.url)
            ext = tldextract.extract(r.url)
            domain = f"{ext.domain}.{ext.suffix}".lower()
        except Exception:
            continue

        # Skip social media, search engines, government registries, encyclopedias
        skip_domains = {
            "linkedin.com", "facebook.com", "instagram.com", "twitter.com",
            "x.com", "youtube.com", "brreg.no", "proff.no", "purehelp.no",
            "1881.no", "gulesider.no", "finn.no", "google.com",
            "wikipedia.org", "bing.com", "duckduckgo.com", "tavily.com",
        }
        if domain in skip_domains:
            continue

        key = r.url.rstrip("/").lower()
        if key not in candidates:
            signals = []
            confidence = 0.3

            # Check if org number appears in snippet
            org_clean = org_number.replace(" ", "")
            if org_clean in r.snippet.replace(" ", ""):
                signals.append("org_number_in_snippet")
                confidence = 0.85

            # Check if company name appears in title
            name_tokens = set(company_name.lower().split())
            title_tokens = set(r.title.lower().split())
            overlap = len(name_tokens & title_tokens) / max(len(name_tokens), 1)
            if overlap > 0.5:
                signals.append("name_in_title")
                confidence = max(confidence, 0.6)

            # Norwegian domain bonus
            if ext.suffix == "no":
                signals.append("norwegian_domain")
                confidence = min(confidence + 0.1, 0.95)

            candidates[key] = {
                "url": r.url,
                "source": f"search_{r.source}",
                "confidence": confidence,
                "signals": signals,
            }

    # Sort by confidence descending
    return sorted(candidates.values(), key=lambda x: x["confidence"], reverse=True)[:5]
