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
) -> list[dict[str, Any]]:
    """Fetch news articles from Google News RSS feed."""
    clean_name = re.sub(
        r"\b(AS|ASA|ANS|DA|ENK|NUF)\b", "", company_name, flags=re.IGNORECASE
    ).strip()

    if not clean_name or len(clean_name) < 3:
        return []

    query = urllib.parse.quote(f'"{clean_name}" Norway')
    url = f"https://news.google.com/rss/search?q={query}&hl=en&gl=NO&ceid=NO:en"

    try:
        import feedparser
        req = urllib.request.Request(url, headers={
            "User-Agent": "builderr-signalpost/1.0 (+https://builderr.ai)",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            content = resp.read()

        feed = feedparser.parse(content)
        articles: list[dict[str, Any]] = []

        for entry in feed.entries[:max_results]:
            published = entry.get("published", "")
            articles.append({
                "title": entry.get("title", ""),
                "url": entry.get("link", ""),
                "published": published,
                "source_name": entry.get("source", {}).get("title", "")
                               if hasattr(entry.get("source", {}), "get")
                               else str(entry.get("source", "")),
                "summary": entry.get("summary", "")[:300],
            })

        return articles
    except Exception:
        return []


def extract_news_from_website(website_value: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract news/press items from crawled company website pages."""
    news_items: list[dict[str, Any]] = []

    for page in website_value.get("pages", []):
        page_url = (page.get("url") or "").lower()
        if any(kw in page_url for kw in ("news", "press", "aktuelt", "nyheter", "blog")):
            text = page.get("main_text_excerpt", "") or ""
            title = page.get("title", "") or ""
            if text and len(text) > 50:
                news_items.append({
                    "title": title,
                    "url": page.get("url", ""),
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
    retrieved_at = utc_now()

    all_news: list[dict[str, Any]] = []

    # 1. Google News RSS
    google_news = fetch_google_news_rss(name)
    for item in google_news:
        item["source_type"] = "google_news_rss"
    all_news.extend(google_news)

    # 2. Company website news pages
    website_ev = profile.get("evidence", {}).get("website", {})
    website_value = website_ev.get("value") or {}
    website_news = extract_news_from_website(website_value)
    all_news.extend(website_news)

    if all_news:
        return evidence(
            "news_activity",
            "available",
            "news_discovery",
            "multiple_sources",
            value={
                "articles": all_news,
                "count": len(all_news),
                "sources": list({n.get("source_type", "unknown") for n in all_news}),
            },
            retrieved_at=retrieved_at,
            content_sha256=hashlib.sha256(
                json.dumps(all_news, sort_keys=True).encode()
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
