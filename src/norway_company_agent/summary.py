"""Profile summary generation.

Uses Gemini Flash (free tier) for natural language summaries,
with a deterministic template fallback when the API is unavailable.
"""
from __future__ import annotations

import os
import json
import hashlib
from typing import Any

from .evidence import evidence, utc_now


def _get_financial_summary(profile: dict[str, Any]) -> str:
    """Build a financial summary string from evidence."""
    financial = profile.get("evidence", {}).get("financials", {})
    records = (financial.get("value") or {}).get("records") or []
    if not records:
        return "No filed annual accounts are available in the registry."

    latest = records[0]
    period = latest.get("period", {})
    parts = []
    if period:
        parts.append(f"Reporting period: {period.get('fraDato', '?')} to {period.get('tilDato', '?')}")

    currency = latest.get("currency", "NOK")
    for label, key in [
        ("Revenue", "revenue"),
        ("Operating result", "operating_result"),
        ("Annual result", "annual_result"),
        ("Total assets", "assets"),
        ("Total equity", "equity"),
        ("Total debt", "debt"),
    ]:
        val = latest.get(key)
        if val is not None:
            if isinstance(val, (int, float)):
                formatted = f"{val:,.0f}" if abs(val) >= 1 else str(val)
                parts.append(f"{label}: {formatted} {currency}")

    return "; ".join(parts) if parts else "Financial data present but not fully parsed."


def _get_leadership_summary(profile: dict[str, Any]) -> str:
    """Build a leadership summary from roles evidence."""
    roles_ev = profile.get("evidence", {}).get("roles", {})
    roles = (roles_ev.get("value") or {}).get("roles") or []
    active = [r for r in roles if not r.get("inactive")]

    if not active:
        return "No active registered role holders."

    key_roles = []
    for r in active[:8]:
        name = r.get("name", "Unknown")
        role = r.get("role") or r.get("group") or "Registered role"
        key_roles.append(f"{name} ({role})")

    return "; ".join(key_roles)


def _get_location_summary(profile: dict[str, Any]) -> str:
    """Build a location summary."""
    addr = profile.get("business_address") or profile.get("postal_address") or {}
    municipality = profile.get("municipality") or ""
    parts = []
    if addr.get("poststed"):
        parts.append(addr["poststed"])
    elif municipality:
        parts.append(municipality)

    locations_ev = profile.get("evidence", {}).get("locations", {})
    locs = (locations_ev.get("value") or {}).get("locations") or []
    if locs:
        parts.append(f"{len(locs)} registered subunit(s)")

    return ", ".join(parts) if parts else "No location information available."


def _get_jobs_summary(profile: dict[str, Any]) -> str:
    """Build a jobs summary."""
    jobs_ev = profile.get("evidence", {}).get("jobs", {})
    if jobs_ev.get("status") != "available":
        return "No current job postings found."

    value = jobs_ev.get("value") or {}
    count = value.get("count", 0)
    return f"{count} job posting(s) found." if count else "No current job postings found."


def _get_news_summary(profile: dict[str, Any]) -> str:
    """Build a news summary."""
    news_ev = profile.get("evidence", {}).get("news_activity", {})
    if news_ev.get("status") != "available":
        return "No recent news found."

    value = news_ev.get("value") or {}
    articles = value.get("articles") or []
    if not articles:
        return "No recent news found."

    headlines = [a.get("title", "") for a in articles[:3] if a.get("title")]
    if headlines:
        return f"{len(articles)} article(s) found. Recent: " + "; ".join(headlines[:3])
    return f"{len(articles)} article(s) found."


def generate_template_summary(profile: dict[str, Any]) -> str:
    """Generate a deterministic template-based summary."""
    name = profile.get("name", "Unknown Company")
    org = profile.get("organisation_number", "")
    legal_form = profile.get("legal_form", "")
    employees = profile.get("employees")
    industry = profile.get("industry") or {}
    industry_desc = industry.get("beskrivelse", "") if isinstance(industry, dict) else str(industry)

    sections = [f"# {name}"]
    sections.append(f"\n**Organisation number:** {org}")
    if legal_form:
        sections.append(f"**Legal form:** {legal_form}")
    if industry_desc:
        sections.append(f"**Primary industry:** {industry_desc}")
    if employees is not None:
        sections.append(f"**Registered employees:** {employees}")

    # Website
    website_ev = profile.get("evidence", {}).get("website", {})
    website_val = website_ev.get("value") or {}
    if website_val.get("final_url"):
        sections.append(f"**Website:** {website_val['final_url']}")
        if website_val.get("description"):
            sections.append(f"\n{website_val['description']}")

    # Financials
    sections.append(f"\n## Financial Summary\n{_get_financial_summary(profile)}")

    # Leadership
    sections.append(f"\n## Leadership\n{_get_leadership_summary(profile)}")

    # Location
    sections.append(f"\n## Location\n{_get_location_summary(profile)}")

    # Jobs
    sections.append(f"\n## Hiring\n{_get_jobs_summary(profile)}")

    # News
    sections.append(f"\n## Recent Activity\n{_get_news_summary(profile)}")

    # Social
    social_ev = profile.get("evidence", {}).get("social_profiles", {})
    social_val = social_ev.get("value") or {}
    profiles_list = social_val.get("profiles") or []
    verified = [p for p in profiles_list if p.get("verified")]
    if verified:
        links = [f"[{p.get('platform', '?')}]({p.get('url', '')})" for p in verified[:5]]
        sections.append(f"\n## Social Profiles\n" + ", ".join(links))

    # Unknown info
    unknowns = []
    for field_name, evidence_key in [
        ("Website", "website"),
        ("Financial data", "financials"),
        ("Roles", "roles"),
        ("Jobs", "jobs"),
        ("News", "news_activity"),
    ]:
        ev = profile.get("evidence", {}).get(evidence_key, {})
        status = ev.get("status", "")
        if status in ("not_available", "not_found", "blocked", "source_error"):
            unknowns.append(field_name)

    if unknowns:
        sections.append(f"\n## Not Available\nThe following could not be found: {', '.join(unknowns)}.")

    return "\n".join(sections)


def generate_llm_summary(profile: dict[str, Any]) -> tuple[str | None, str]:
    """Generate a summary using Gemini Flash or Groq free tier.

    Returns (summary_text, method_name) or (None, "").
    """
    template = generate_template_summary(profile)
    prompt = f"""You are a company research analyst. Given the following structured data about a Norwegian company, write a concise professional profile summary (200-400 words).

Rules:
- Only state facts that appear in the data below. Never invent or assume.
- Explicitly note what information is missing or unavailable.
- Use a neutral, professional tone.
- Cite the type of source for each fact (e.g., "official registry", "company website", "job platform").
- Do NOT fabricate financial figures.

Company Data:
{template}

Write the summary now:"""

    # 1. Try Gemini Flash (free tier from Google AI Studio)
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if gemini_key:
        try:
            from google import genai

            client = genai.Client(api_key=gemini_key)
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt,
            )
            if response.text:
                return response.text, "gemini_2.0_flash_free"
        except Exception:
            pass

    # 2. Try Groq (free tier: Llama 3.3 70B from console.groq.com)
    groq_key = os.environ.get("GROQ_API_KEY", "").strip()
    if groq_key:
        try:
            import urllib.request
            url = "https://api.groq.com/openai/v1/chat/completions"
            payload = json.dumps({
                "model": "llama-3.3-70b-versatile",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 800,
                "temperature": 0.2,
            }).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=payload,
                headers={
                    "Authorization": f"Bearer {groq_key}",
                    "Content-Type": "application/json",
                    "User-Agent": "BuilderrAgent/1.0",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            content = data["choices"][0]["message"]["content"]
            if content:
                return content, "groq_llama_3.3_70b_free"
        except Exception:
            pass

    return None, ""


def generate_summary(profile: dict[str, Any]) -> dict[str, Any]:
    """Generate the best available summary for a company profile.

    Tries LLM first (Gemini or Groq free tier), falls back to deterministic template.
    """
    retrieved_at = utc_now()

    llm_summary, method = generate_llm_summary(profile)

    if llm_summary:
        summary_text = llm_summary
    else:
        summary_text = generate_template_summary(profile)
        method = "deterministic_template"

    return evidence(
        "profile_summary",
        "available",
        "generated_summary",
        "local_synthesis",
        value={
            "summary": summary_text,
            "method": method,
            "company_name": profile.get("name", ""),
            "organisation_number": profile.get("organisation_number", ""),
        },
        retrieved_at=retrieved_at,
        content_sha256=hashlib.sha256(summary_text.encode()).hexdigest(),
    )
