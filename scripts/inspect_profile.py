#!/usr/bin/env python3
"""Signalpost Profile Inspector — Evaluator UX Tool.

Provides an interactive and beautiful command-line interface to inspect
Norwegian company profiles, audit evidence hashes, and review batch coverage.

Usage:
    # Inspect a specific company by organisation number
    uv run python scripts/inspect_profile.py --org 923609016

    # Search by company name in existing output
    uv run python scripts/inspect_profile.py --search "Equinor"

    # View overall summary of a run directory
    uv run python scripts/inspect_profile.py --dir out/smoke

    # Export a clean JSON profile
    uv run python scripts/inspect_profile.py --org 923609016 --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Ensure UTF-8 output on all operating systems (Windows consoles)
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Color codes
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
MAGENTA = "\033[35m"
BLUE = "\033[34m"
WHITE = "\033[37m"


def badge(status: str) -> str:
    s = (status or "").lower()
    if s in ("available", "complete"):
        return f"{GREEN}[AVAILABLE]{RESET}"
    elif s in ("not_available", "not_found"):
        return f"{YELLOW}[NOT AVAILABLE]{RESET}"
    elif s == "ambiguous":
        return f"{MAGENTA}[AMBIGUOUS]{RESET}"
    elif s == "not_applicable":
        return f"{DIM}[N/A]{RESET}"
    elif s in ("blocked", "blocked_robots", "blocked_policy"):
        return f"{RED}[BLOCKED]{RESET}"
    elif s in ("failed", "source_error", "submission_error"):
        return f"{RED}[FAILED]{RESET}"
    return f"{WHITE}[{status.upper()}]{RESET}"


def load_profiles(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return rows


def find_profile_file(dir_path: Path | None = None) -> Path | None:
    candidates = [
        dir_path / "profiles.jsonl" if dir_path else None,
        Path("out/production/profiles.jsonl"),
        Path("out/submission/profiles.jsonl"),
        Path("out/smoke/profiles.jsonl"),
        Path("out/profiles.jsonl"),
    ]
    for c in candidates:
        if c and c.is_file():
            return c
    return None


def print_company_card(profile: dict[str, Any]) -> None:
    org = profile.get("organisation_number", "Unknown")
    name = profile.get("name", "Unknown Company")
    form = profile.get("organisasjonsform", "AS")
    municipality = profile.get("municipality", "")
    addr = profile.get("business_address") or profile.get("postal_address") or {}
    addr_str = addr.get("adresse", [""])[0] if isinstance(addr.get("adresse"), list) else addr.get("adresse", "")
    poststed = addr.get("poststed", municipality)

    ev = profile.get("evidence", {})

    print(f"\n{CYAN}╔{'═' * 76}╗{RESET}")
    print(f"{CYAN}║{RESET} {BOLD}{name.upper():<58}{RESET} {DIM}({org}){RESET} {CYAN}║{RESET}")
    print(f"{CYAN}╠{'═' * 76}╣{RESET}")
    print(f"{CYAN}║{RESET} Form: {BOLD}{form:<10}{RESET} Location: {poststed} ({municipality})")
    if addr_str:
        print(f"{CYAN}║{RESET} Address: {addr_str}, {poststed}")
    print(f"{CYAN}╟{'─' * 76}╢{RESET}")

    # Core claims summary
    print(f"{CYAN}║{RESET} {BOLD}DISCOVERY MODULE STATUSES:{RESET}")

    modules_to_show = [
        ("Official Registry", "registry"),
        ("Live Entity State", "registry_live"),
        ("Verified Website", "website"),
        ("Annual Accounts", "financials"),
        ("Leadership Roles", "roles"),
        ("Subunit Locations", "locations"),
        ("Job Postings", "jobs"),
        ("News & Activity", "news_activity"),
        ("Social Profiles", "social_profiles"),
        ("Annual Report PDF", "annual_report_pdf"),
        ("Profile Summary", "profile_summary"),
    ]

    for label, mod_key in modules_to_show:
        record = ev.get(mod_key, {})
        status = record.get("status", "not_checked")
        b = badge(status)
        details = ""
        if mod_key == "website" and status == "available":
            details = (record.get("value") or {}).get("canonical_domain") or profile.get("website") or ""
        elif mod_key == "financials" and status == "available":
            recs = (record.get("value") or {}).get("records") or []
            if recs:
                rev = recs[0].get("revenue")
                curr = recs[0].get("currency", "NOK")
                details = f"Turnover: {rev:,.0f} {curr}" if isinstance(rev, (int, float)) else "Accounts filed"
        elif mod_key == "roles" and status == "available":
            roles = (record.get("value") or {}).get("roles") or []
            ceo = next((r.get("name") for r in roles if "daglig leder" in str(r.get("role") or "").lower()), None)
            details = f"CEO: {ceo}" if ceo else f"{len(roles)} registered role holders"
        elif mod_key == "jobs" and status == "available":
            cnt = (record.get("value") or {}).get("count", 0)
            details = f"{cnt} active job posting(s)"
        elif mod_key == "news_activity" and status == "available":
            cnt = (record.get("value") or {}).get("count", 0)
            details = f"{cnt} recent article(s)"

        print(f"{CYAN}║{RESET}   {label:<22} {b:<25} {DIM}{details[:25]}{RESET}")

    # Financial breakdown if present
    fin_val = (ev.get("financials", {}).get("value") or {}).get("records", [])
    if fin_val:
        print(f"{CYAN}╟{'─' * 76}╢{RESET}")
        print(f"{CYAN}║{RESET} {BOLD}FINANCIAL TRAJECTORY:{RESET}")
        print(f"{CYAN}║{RESET}   {'Year':<6} {'Revenue (NOK)':<18} {'Operating Result':<18} {'Equity':<16}")
        for r in fin_val[:3]:
            year = str(r.get("year") or (r.get("period", {}).get("tilDato", "")[:4]) or "?")
            rev = f"{r.get('revenue'):,.0f}" if isinstance(r.get("revenue"), (int, float)) else "N/A"
            op = f"{r.get('operating_result'):,.0f}" if isinstance(r.get("operating_result"), (int, float)) else "N/A"
            eq = f"{r.get('equity'):,.0f}" if isinstance(r.get("equity"), (int, float)) else "N/A"
            print(f"{CYAN}║{RESET}   {year:<6} {rev:<18} {op:<18} {eq:<16}")

    # Summary preview if available
    summary_text = (ev.get("profile_summary", {}).get("value") or {}).get("summary")
    if summary_text:
        print(f"{CYAN}╟{'─' * 76}╢{RESET}")
        print(f"{CYAN}║{RESET} {BOLD}EXECUTIVE SUMMARY:{RESET}")
        for line in summary_text.strip().splitlines()[:6]:
            print(f"{CYAN}║{RESET}   {line[:72]}")
        if len(summary_text.strip().splitlines()) > 6:
            print(f"{CYAN}║{RESET}   {DIM}... [summary continues]{RESET}")

    # Evidence audit preview
    print(f"{CYAN}╟{'─' * 76}╢{RESET}")
    print(f"{CYAN}║{RESET} {BOLD}AUDIT TRAIL & CONTENT HASHES:{RESET}")
    for mod_key in ("registry", "financials", "website", "roles"):
        record = ev.get(mod_key)
        if record and record.get("status") == "available":
            src_url = record.get("source_url") or "official_registry"
            sha = (record.get("content_sha256") or "")[:12] + "..."
            retrieved = record.get("retrieved_at", "")[:19]
            print(f"{CYAN}║{RESET}   {mod_key:<12} {DIM}{retrieved}{RESET}  SHA:{GREEN}{sha:<15}{RESET}  {src_url[:30]}")

    print(f"{CYAN}╚{'═' * 76}╝{RESET}\n")


def print_directory_summary(dir_path: Path) -> None:
    profiles_file = dir_path / "profiles.jsonl"
    envelopes_file = dir_path / "envelopes.jsonl"
    report_file = dir_path / "run-report.json"

    if not profiles_file.exists():
        print(f"{RED}Error:{RESET} Could not find profiles.jsonl in {dir_path}")
        return

    profiles = load_profiles(profiles_file)
    n = len(profiles)

    print(f"\n{CYAN}{'═' * 60}{RESET}")
    print(f"{BOLD}SIGNALPOST RUN SUMMARY: {dir_path.resolve()}{RESET}")
    print(f"{CYAN}{'═' * 60}{RESET}")
    print(f"Total Profiles Emitted: {BOLD}{n}{RESET}")

    if report_file.exists():
        try:
            rep = json.loads(report_file.read_text(encoding="utf-8"))
            ops = rep.get("operations", {})
            print(f"Total Outbound Requests: {ops.get('requests', 'N/A')}")
            print(f"Search Queries Used:    {ops.get('search_queries_used', 'N/A')}")
            print(f"Declared Third-Party Cost: {GREEN}${ops.get('third_party_cost_usd', 0.0):.2f}{RESET}")
            if ops.get("p50_ms"):
                print(f"Latency P50: {ops.get('p50_ms')} ms | P95: {ops.get('p95_ms')} ms")
        except Exception:
            pass

    print(f"\n{BOLD}Module Availability Rates ({n} companies):{RESET}")
    for mod_name, label in [
        ("registry", "Brreg Registry Identity"),
        ("financials", "Annual Accounts"),
        ("website", "Verified Official Website"),
        ("roles", "Leadership & Board Roles"),
        ("locations", "Subunit Locations"),
        ("jobs", "Job Postings Discovered"),
        ("news_activity", "News & Media Mentions"),
        ("social_profiles", "Verified Social Profiles"),
        ("annual_report_pdf", "Annual Report PDF"),
        ("profile_summary", "Executive Summary"),
    ]:
        available = sum(1 for p in profiles if (p.get("evidence", {}).get(mod_name, {}).get("status") == "available"))
        pct = (available / n * 100) if n else 0
        bar = "█" * int(pct // 5) + "░" * (20 - int(pct // 5))
        print(f"  {label:<28} [{bar}] {pct:>5.1f}% ({available}/{n})")

    print(f"{CYAN}{'═' * 60}{RESET}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect Norwegian company profiles and run metrics.")
    parser.add_argument("--org", help="9-digit organisation number to inspect")
    parser.add_argument("--search", help="Search company name")
    parser.add_argument("--dir", help="Path to run output directory (e.g. out/smoke)")
    parser.add_argument("--file", help="Explicit path to profiles.jsonl")
    parser.add_argument("--json", action="store_true", help="Output full JSON instead of terminal card")
    args = parser.parse_args()

    target_dir = Path(args.dir) if args.dir else None

    # Directory summary mode
    if args.dir and not (args.org or args.search):
        print_directory_summary(target_dir)
        return

    # Find profiles file
    if args.file:
        profile_path = Path(args.file)
    else:
        profile_path = find_profile_file(target_dir)

    if not profile_path or not profile_path.is_file():
        print(f"{RED}Error:{RESET} Could not find profiles.jsonl. Run the pipeline first or specify --file.")
        sys.exit(1)

    profiles = load_profiles(profile_path)
    if not profiles:
        print(f"{YELLOW}Warning:{RESET} No profiles found in {profile_path}")
        sys.exit(0)

    matched = []
    if args.org:
        target_org = "".join(c for c in args.org if c.isdigit())
        matched = [p for p in profiles if p.get("organisation_number") == target_org]
    elif args.search:
        q = args.search.casefold()
        matched = [p for p in profiles if q in (p.get("name") or "").casefold()]
    else:
        # Default: show the first company
        matched = profiles[:1]

    if not matched:
        print(f"{YELLOW}No matching company found in {profile_path}.{RESET}")
        sys.exit(0)

    for p in matched:
        if args.json:
            print(json.dumps(p, indent=2, ensure_ascii=False))
        else:
            print_company_card(p)


if __name__ == "__main__":
    main()
