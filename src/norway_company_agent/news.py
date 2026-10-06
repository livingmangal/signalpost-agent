"""News and public activity discovery.

Sources:
1. Google News RSS (free, no key)
2. Company website news/press pages (already crawled)
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.parse
import urllib.request
from typing import Any

from .evidence import evidence, utc_now


def fetch_google_news_rss(
    company_name: str,
    max_results: int = 10,
    municipality: str = "",
) -> list[dict[str, Any]]:
    """Fetch news articles from Google News RSS feed localized for Norway."""
    clean_name = re.sub(
        r"\b(AS|ASA|ANS|DA|ENK|NUF)\b", "", company_name, flags=re.IGNORECASE
    ).strip()

    if not clean_name or len(clean_name) < 3:
        return []

    articles: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    queries = [urllib.parse.quote(f'"{clean_name}"')]
    if municipality and municipality.strip():
        clean_muni = re.sub(r"\d+", "", municipality).strip()
        if len(clean_muni) >= 3:
            queries.append(urllib.parse.quote(f'"{clean_name}" {clean_muni}'))

    import feedparser
    for q in queries[:2]:
        url = f"https://news.google.com/rss/search?q={q}&hl=no&gl=NO&ceid=NO:no"
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            })
            with urllib.request.urlopen(req, timeout=5) as resp:
                content = resp.read()

            feed = feedparser.parse(content)
            for entry in feed.entries:
                link = entry.get("link", "")
                if link and link not in seen_urls:
                    seen_urls.add(link)
                    raw_title = entry.get("title", "").strip()
                    clean_title = raw_title
                    while re.search(r"\s*-\s*[^-]+$", clean_title):
                        clean_title = re.sub(r"\s*-\s*[^-]+$", "", clean_title).strip()
                    if not clean_title:
                        clean_title = raw_title

                    raw_source = entry.get("source", {}).get("title", "") if hasattr(entry.get("source", {}), "get") else str(entry.get("source", ""))
                    clean_source = str(raw_source or "").strip().lower()

                    clean_summary = re.sub(r"<[^>]+>", " ", entry.get("summary", "") or "")
                    clean_summary = re.sub(r"\s+", " ", clean_summary).strip()[:300]

                    published_parsed = entry.get("published_parsed")
                    if published_parsed:
                        published = time.strftime("%Y-%m-%dT%H:%M:%SZ", published_parsed)
                    else:
                        published = str(entry.get("published") or entry.get("updated") or "").strip()

                    articles.append({
                        "title": clean_title,
                        "url": link,
                        "published": published,
                        "source_name": clean_source,
                        "summary": clean_summary,
                    })
                    if len(articles) >= max_results:
                        break
            if len(articles) >= max_results:
                break
        except Exception:
            continue

    return articles[:max_results]


def _extract_page_date(page: dict[str, Any]) -> str:
    """Extract ISO publication date from crawled page metadata or text."""
    if page.get("published"):
        return str(page["published"]).strip()

    text = page.get("main_text_excerpt", "") or ""
    # Check for Norwegian publication date pattern: e.g. "Publisert 22.09.2025" or "22. september 2025"
    m_nor = re.search(r"(?:publisert|oppdatert|dato)[:\s]+(\d{1,2})\.(\d{1,2})\.(\d{4})", text, re.IGNORECASE)
    if m_nor:
        day, month, year = m_nor.groups()
        return f"{year}-{int(month):02d}-{int(day):02d}T00:00:00Z"

    # Check for ISO date in text: YYYY-MM-DD
    m_iso = re.search(r"\b(202[0-9]-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01]))\b", text)
    if m_iso:
        return f"{m_iso.group(1)}T00:00:00Z"

    # Check for URL date patterns: /2025/09/22/ or /2025-09-22
    url = page.get("url", "")
    m_url = re.search(r"/(202[0-9])/(0[1-9]|1[0-2])/(0[1-9]|[12][0-9]|3[01])/", url)
    if m_url:
        y, m, d = m_url.groups()
        return f"{y}-{m}-{d}T00:00:00Z"

    return ""


def extract_news_from_website(website_value: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract news/press items from crawled company website pages."""
    news_items: list[dict[str, Any]] = []

    for page in website_value.get("pages", []):
        page_url = (page.get("url") or "").lower()
        if any(kw in page_url for kw in ("news", "press", "aktuelt", "nyheter", "presse", "blog", "media")):
            text = page.get("main_text_excerpt", "") or ""
            title = page.get("title", "") or ""
            if text and len(text) > 30:
                published = _extract_page_date(page)
                news_items.append({
                    "title": title,
                    "url": page.get("url", ""),
                    "published": published,
                    "text_excerpt": text[:500],
                    "source_type": "company_website_news",
                })

    return news_items[:10]


def fetch_company_news(
    profile: dict[str, Any],
) -> dict[str, Any]:
    """Fetch all discoverable news for a company.

    Combines Google News RSS with company website news pages.
    Returns an evidence record.
    """
    name = profile.get("name", "")
    municipality = profile.get("municipality", "")
    retrieved_at = utc_now()

    all_news: list[dict[str, Any]] = []

    # 1. Google News RSS (Norwegian edition)
    google_news = fetch_google_news_rss(name, municipality=municipality)
    for item in google_news:
        item["source_type"] = "google_news_rss"
    all_news.extend(google_news)

    # 2. Company website news pages
    website_ev = profile.get("evidence", {}).get("website", {})
    website_value = website_ev.get("value") or {}
    website_news = extract_news_from_website(website_value)
    all_news.extend(website_news)

    # 3. Free search fallback for Norwegian news if RSS and website found 0 items
    if not all_news:
        clean_name = re.sub(r"\b(AS|ASA|ANS|DA|ENK|NUF)\b", "", name, flags=re.IGNORECASE).strip()
        if clean_name and len(clean_name) >= 3:
            try:
                from .search_api import search_duckduckgo
                search_items = search_duckduckgo(f'"{clean_name}" nyheter', max_results=3)
                for s in search_items:
                    pub_match = re.search(r"\b(202[0-9]-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01]))\b", s.snippet)
                    pub_date = f"{pub_match.group(1)}T00:00:00Z" if pub_match else ""
                    all_news.append({
                        "title": s.title,
                        "url": s.url,
                        "summary": s.snippet[:300],
                        "published": pub_date,
                        "source_name": s.source,
                        "source_type": "search_news_fallback",
                    })
            except Exception:
                pass

    # Deduplicate and stably sort news articles
    deduped = {}
    for n in all_news:
        key = str(n.get("url") or n.get("title") or "").strip()
        if key and key not in deduped:
            deduped[key] = n
    all_news = sorted(deduped.values(), key=lambda a: (str(a.get("title") or ""), str(a.get("url") or "")))
    dated_articles = [n for n in all_news if n.get("published")]
    dated_articles.sort(key=lambda a: str(a.get("published") or ""), reverse=True)
    latest_dated = dated_articles[0] if dated_articles else (all_news[0] if all_news else None)

    if all_news:
        return evidence(
            "news_activity",
            "available",
            "news_discovery",
            "multiple_sources",
            value={
                "articles": all_news,
                "count": len(all_news),
                "latest_dated_article": latest_dated,
                "sources": sorted(list({n.get("source_type", "unknown") for n in all_news})),
            },
            retrieved_at=retrieved_at,
            content_sha256=hashlib.sha256(
                json.dumps([{"title": a.get("title"), "url": a.get("url")} for a in all_news], sort_keys=True).encode("utf-8")
            ).hexdigest(),
        )
    else:
        return evidence(
            "news_activity",
            "not_available",
            "news_discovery",
            "multiple_sources",
            note="No recent news articles found for this company.",
            retrieved_at=retrieved_at,
        )
