"""Reviews and aggregate ratings connector for Norwegian trades and local services."""
from __future__ import annotations

import json
import re
import unicodedata
from bs4 import BeautifulSoup


def slug(value: object) -> str:
    text = str(value or "").translate(str.maketrans({"ø": "o", "å": "a", "æ": "ae", "Ø": "O", "Å": "A", "Æ": "AE"}))
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().casefold()
    return "-".join(re.findall(r"[a-z0-9]+", text))


def extract_aggregate_rating(raw: bytes) -> tuple[float, int, str | None]:
    soup = BeautifulSoup(raw, "html.parser")
    for node in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(node.string or node.get_text() or "{}")
        except Exception:
            continue
        candidates = data if isinstance(data, list) else [data]
        for item in candidates:
            rating = (item or {}).get("aggregateRating") if isinstance(item, dict) else None
            if not isinstance(rating, dict):
                continue
            value, count = rating.get("ratingValue"), rating.get("ratingCount") or rating.get("reviewCount")
            if value is not None and count is not None:
                review_link = soup.find("a", href=re.compile(r"search\.google\.com/local/reviews"))
                return float(value), int(count), review_link.get("href") if review_link else None
    raise ValueError("no aggregate rating")
