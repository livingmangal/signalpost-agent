#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import threading
import time
import urllib.error
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT / "src"))

from norway_company_agent.connectors.linkedin import (
    canonical_company_url,
    discovery_identity,
    extract_profile,
    legal_name_profile_url,
    normalized_company,
    normalized_full_name,
    official_site_aliases,
    parse_exact_typeahead,
    registered_domain,
    LEGAL_SUFFIXES,
)
from scripts.run_linkedin_guest_jobs_connector import fetch as fetch_jobs
from scripts.run_linkedin_guest_experiment import fetch


def job_company_urls(raw: bytes) -> set[str]:
    soup = BeautifulSoup(raw, "html.parser")
    return {
        url
        for link in soup.select("h4.base-search-card__subtitle a[href]")
        if (url := canonical_company_url(str(link.get("href") or "")))
    }




class SnapshotCache:
    def __init__(self, path: Path):
        self.path = path
        self.path.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()

    def get(self, url: str, timeout: float, *, jobs: bool = False) -> tuple[bytes, str, str]:
        request_hash = hashlib.sha256(url.encode()).hexdigest()
        snapshot = self.path / f"{request_hash}.bin"
        if snapshot.exists():
            raw = snapshot.read_bytes()
        else:
            raw = fetch_jobs(url, timeout) if jobs else fetch(url, timeout)[0]
            with self.lock:
                if not snapshot.exists():
                    snapshot.write_bytes(raw)
        return raw, hashlib.sha256(raw).hexdigest(), str(snapshot)


def discover_one(profile: dict, cache: SnapshotCache, timeout: float, delay: float, fuzzy: bool = False) -> dict:
    org = str(profile["organisation_number"])
    legal_name = str(profile.get("name") or "")
    result = {"organisation_number": org, "name": legal_name, "typeahead": [], "candidates": [], "accepted": None, "errors": []}
    queries = [(legal_name, False)] + [(alias, True) for alias in official_site_aliases(profile) if fuzzy]
    for query, is_alias in queries:
        query_url = "https://www.linkedin.com/jobs-guest/api/typeaheadHits?" + urllib.parse.urlencode(
            {"typeaheadType": "COMPANY", "query": query}
        )
        try:
            raw, _, typeahead_snapshot = cache.get(query_url, timeout, jobs=True)
            for item in parse_exact_typeahead(raw, query):
                item["query"] = query
                item["official_site_alias"] = is_alias
                item["typeahead_snapshot_path"] = typeahead_snapshot
                result["typeahead"].append(item)
        except Exception as exc:
            result["errors"].append(f"typeahead {type(exc).__name__}: {str(exc)[:140]}")
    if not result["typeahead"]:
        return result

    candidates: dict[str, set[str]] = {}
    for query, is_alias in queries:
        query_profile_url = legal_name_profile_url(query)
        if query_profile_url:
            source = f"official_site_alias:{query}" if is_alias else "legal_name_slug"
            candidates.setdefault(canonical_company_url(query_profile_url) or query_profile_url, set()).add(source)
    for item in result["typeahead"][:2]:
        jobs_url = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?" + urllib.parse.urlencode(
            {"f_C": item["linkedin_company_id"], "location": "Norway", "start": 0}
        )
        try:
            raw, _, snapshot = cache.get(jobs_url, timeout, jobs=True)
            for url in job_company_urls(raw):
                candidates.setdefault(url, set()).add("company_id_job_link")
                if item.get("official_site_alias"):
                    candidates[url].add(f"official_site_alias:{item['query']}")
            item["jobs_snapshot_path"] = snapshot
        except Exception as exc:
            result["errors"].append(f"company_id {item['linkedin_company_id']} {type(exc).__name__}: {str(exc)[:120]}")
        time.sleep(max(0, delay))

    for candidate, sources in candidates.items():
        candidate_row = {"url": candidate, "sources": sorted(sources), "accepted": False}
        try:
            snapshot = cache.path / f"{hashlib.sha256(candidate.encode()).hexdigest()}-profile.html"
            if snapshot.exists():
                raw = snapshot.read_bytes()
                final_url = candidate
            else:
                raw, final_url = fetch(candidate, timeout)
                with cache.lock:
                    snapshot.write_bytes(raw)
            digest = hashlib.sha256(raw).hexdigest()
            linkedin_profile = extract_profile(raw)
            identity = discovery_identity(profile, linkedin_profile, sources)
            candidate_row.update(
                {
                    "resolved_url": linkedin_profile.get("page_url") or canonical_company_url(final_url),
                    "profile": linkedin_profile,
                    "identity": identity,
                    "content_sha256": digest,
                    "snapshot_path": str(snapshot),
                    "accepted": identity["exact_entity"],
                }
            )
            if identity["exact_entity"]:
                result["accepted"] = candidate_row
                result["candidates"].append(candidate_row)
                break
        except urllib.error.HTTPError as exc:
            candidate_row["error"] = f"HTTP {exc.code}"
        except Exception as exc:
            candidate_row["error"] = f"{type(exc).__name__}: {str(exc)[:140]}"
        result["candidates"].append(candidate_row)
        time.sleep(max(0, delay))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Discover exact LinkedIn company profiles from a frozen Norwegian company corpus.")
    parser.add_argument("--profiles", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--cache-dir", required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--delay", type=float, default=0.1)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--fuzzy", action="store_true", help="Also query exact aliases found on verified official websites.")
    args = parser.parse_args()
    profiles = [json.loads(line) for line in Path(args.profiles).read_text().splitlines() if line.strip()]
    cache = SnapshotCache(Path(args.cache_dir))
    results = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {pool.submit(discover_one, profile, cache, args.timeout, args.delay, args.fuzzy): profile for profile in profiles}
        for index, future in enumerate(as_completed(futures), 1):
            results.append(future.result())
            if index % 50 == 0:
                print(f"{index}/{len(profiles)} accepted={sum(bool(item['accepted']) for item in results)}", flush=True)
    results.sort(key=lambda item: next(i for i, profile in enumerate(profiles) if str(profile["organisation_number"]) == item["organisation_number"]))
    retrieved_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    observations = []
    for row in results:
        accepted = row.get("accepted")
        if not accepted:
            continue
        identity = accepted["identity"]
        profile_url = accepted["resolved_url"]
        observations.append(
            {
                "id": "linkedin-discovered-handle-" + hashlib.sha256(f"{row['organisation_number']}|{profile_url}".encode()).hexdigest()[:24],
                "organisation_number": row["organisation_number"],
                "platform": "linkedin",
                "signal_type": "profile_handle",
                "source_url": profile_url,
                "profile_url": profile_url,
                "linkedin_company_ids": sorted({item["linkedin_company_id"] for item in row.get("typeahead") or []}),
                "retrieved_at": retrieved_at,
                "content_sha256": accepted["content_sha256"],
                "exact_entity": True,
                "identity_proof": [{"type": "linkedin_discovery_identity", "value": identity}],
                "acquisition_mode": "unofficial_api_experiment",
                "rights_status": "experimental",
                "source_class": "professional_network",
                "strategy": "verified_handle_extraction",
            }
        )
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text("".join(json.dumps(item, ensure_ascii=False) + "\n" for item in observations), encoding="utf-8")
    report = {
        "connector": "linkedin_exact_company_discovery_v1",
        "companies": len(profiles),
        "exact_typeahead_matches": sum(bool(item["typeahead"]) for item in results),
        "candidate_profiles": sum(len(item["candidates"]) for item in results),
        "accepted_profiles": len(observations),
        "fuzzy_alias_mode": args.fuzzy,
        "results": results,
        "publishable": False,
        "claim_boundary": "Discovery output is experimental pending LinkedIn source-rights approval; exact-entity gates remain mandatory.",
    }
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "results"}, indent=2))


if __name__ == "__main__":
    main()
