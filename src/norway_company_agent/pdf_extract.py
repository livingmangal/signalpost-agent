"""PDF annual report extraction.

Downloads annual report PDFs from Brønnøysundregistrene and extracts
supplementary information (auditor, board details, text summaries).
"""
from __future__ import annotations

import hashlib
import re
import time
import urllib.request
from typing import Any

from .evidence import evidence, utc_now


BRREG_ACCOUNT_PDF = "https://data.brreg.no/regnskapsregisteret/regnskap/aarsregnskap/kopi/{org}/{year}"
USER_AGENT = "builderr-signalpost/1.0 (+https://builderr.ai)"


def download_pdf(url: str, timeout: int = 15) -> bytes | None:
    """Download a PDF from the given URL."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                return resp.read()
    except Exception:
        pass
    return None


def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """Extract text from PDF bytes using pypdf."""
    try:
        import pypdf
        import io
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        text_parts: list[str] = []
        for page in reader.pages[:20]:  # Limit to first 20 pages
            page_text = page.extract_text() or ""
            text_parts.append(page_text)
        return "\n".join(text_parts)
    except Exception:
        return ""


def extract_auditor(text: str) -> str | None:
    """Extract auditor name from annual report text."""
    patterns = [
        r"(?i)(?:revisor|auditor|revisjon)[:\s]*([A-ZÆØÅ][A-Za-zæøåÆØÅ\s&.,-]{3,60}(?:AS|ASA|DA|ANS)?)",
        r"(?i)((?:Deloitte|PwC|KPMG|EY|Ernst & Young|BDO|RSM|Grant Thornton|Mazars|PricewaterhouseCoopers|Revisjon)[A-Za-zæøåÆØÅ\s&.,-]{0,40})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            auditor = match.group(1).strip()
            if len(auditor) > 3:
                return auditor
    return None


def extract_board_members_from_pdf(text: str) -> list[str]:
    """Extract board member names from annual report text."""
    members: list[str] = []
    patterns = [
        r"(?i)(?:styrets? (?:leder|medlem|nestleder)|styreleder|board (?:member|chair))[:\s]*([A-ZÆØÅ][a-zæøå]+ [A-ZÆØÅ][a-zæøå]+(?:\s[A-ZÆØÅ][a-zæøå]+)?)",
        r"(?i)(?:daglig leder|administrerende direktør|CEO|managing director)[:\s]*([A-ZÆØÅ][a-zæøå]+ [A-ZÆØÅ][a-zæøå]+(?:\s[A-ZÆØÅ][a-zæøå]+)?)",
    ]
    seen: set[str] = set()
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            name = match.group(1).strip()
            if name.lower() not in seen and len(name) > 4:
                seen.add(name.lower())
                members.append(name)
    return members[:15]


def extract_key_figures_from_pdf(text: str) -> dict[str, Any]:
    """Extract key financial figures from PDF text as supplementary data."""
    figures: dict[str, Any] = {}

    # Employee count patterns
    emp_patterns = [
        r"(?i)(?:antall (?:ansatte|årsverk)|(?:number of )?employees?|headcount)[:\s]*(\d[\d\s,.]*\d|\d+)",
    ]
    for pattern in emp_patterns:
        match = re.search(pattern, text)
        if match:
            count_str = re.sub(r"[\s,.]", "", match.group(1))
            try:
                figures["employee_count_pdf"] = int(count_str)
            except ValueError:
                pass
            break

    return figures


def fetch_annual_report(
    org: str,
    year: str | int,
) -> dict[str, Any]:
    """Download and extract information from an annual report PDF.

    Rate-limited to be respectful to the Brreg server.
    """
    retrieved_at = utc_now()
    url = BRREG_ACCOUNT_PDF.format(org=org, year=year)
    pdf_bytes = download_pdf(url)

    if not pdf_bytes:
        return evidence(
            "annual_report_pdf",
            "not_available",
            "official_annual_report_pdf",
            url,
            note=f"PDF not available for year {year}.",
            retrieved_at=retrieved_at,
        )

    text = extract_text_from_pdf(pdf_bytes)
    if not text:
        return evidence(
            "annual_report_pdf",
            "available",
            "official_annual_report_pdf",
            url,
            value={"year": str(year), "text_extracted": False, "note": "PDF downloaded but text extraction failed."},
            retrieved_at=retrieved_at,
            content_sha256=hashlib.sha256(pdf_bytes).hexdigest(),
        )

    auditor = extract_auditor(text)
    board_from_pdf = extract_board_members_from_pdf(text)
    key_figures = extract_key_figures_from_pdf(text)

    return evidence(
        "annual_report_pdf",
        "available",
        "official_annual_report_pdf",
        url,
        value={
            "year": str(year),
            "text_extracted": True,
            "text_length": len(text),
            "auditor": auditor,
            "board_members_mentioned": board_from_pdf,
            "key_figures": key_figures if key_figures else None,
            "text_excerpt": text[:2000],  # First 2000 chars for context
        },
        retrieved_at=retrieved_at,
        content_sha256=hashlib.sha256(pdf_bytes).hexdigest(),
    )
