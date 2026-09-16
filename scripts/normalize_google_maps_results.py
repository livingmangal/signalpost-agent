#!/usr/bin/env python3
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import math
import re
import urllib.parse
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT / "src"))

from norway_company_agent.connectors.maps import (
    GENERIC_MAP_TOKENS,
    LEGAL_STOP,
    VERIFIED_TRADE_NAMES,
    candidate_score,
    meaningful_name_tokens,
    normalized_phone,
    registered_domain,
    review_label,
    tokens,
)


def result_hash(candidate: dict) -> str:
    return hashlib.sha256(json.dumps(candidate, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def normalize_company(profile: dict, candidates: list[dict], retrieved_at: str) -> tuple[list[dict], dict]:
    unique = {}
    for item in candidates:
        key = str(item.get("place_id") or item.get("data_id") or item.get("link") or result_hash(item))
        unique[key] = item
    candidates = list(unique.values())
    assessed = [{"candidate": item, "assessment": candidate_score(profile, item)} for item in candidates]
    accepted = [item for item in assessed if item["assessment"]["accepted"]]
    accepted.sort(key=lambda item: (-item["assessment"]["score"], str(item["candidate"].get("data_id") or "")))
    if not accepted:
        return [], {"status": "no_exact_match", "candidates": len(candidates)}
    if len(accepted) > 1 and accepted[0]["assessment"]["score"] == accepted[1]["assessment"]["score"]:
        return [], {"status": "ambiguous_exact_match", "candidates": len(candidates)}

    chosen = accepted[0]
    candidate = chosen["candidate"]
    assessment = chosen["assessment"]
    digest = result_hash(candidate)
    org = str(profile["organisation_number"])
    source_url = str(candidate.get("link") or "")
    proof = [
        {"type": "maps_title_name_score", "value": assessment["name_score"]},
        {"type": "registry_address_match", "value": assessment["address_match"]},
        {"type": "registry_postcode_city_match", "value": assessment["postcode_city_match"]},
        {"type": "registry_phone_match", "value": assessment["phone_match"]},
        {"type": "verified_website_domain_match", "value": assessment["website_match"]},
        {"type": "independently_verified_trade_name", "value": assessment.get("trade_name_match"), "source_url": assessment.get("trade_name_source")},
    ]
    common = {
        "organisation_number": org,
        "platform": "google_places",
        "source_url": source_url,
        "retrieved_at": retrieved_at,
        "content_sha256": digest,
        "exact_entity": True,
        "identity_proof": proof,
        "acquisition_mode": "unofficial_api_experiment",
        "rights_status": "review_required",
    }
    evidence = (
        f"{candidate.get('title')}; {candidate.get('address')}; {candidate.get('phone')}; "
        f"rating={candidate.get('review_rating')}; reviews={candidate.get('review_count')}"
    )
    observations = [{
        **common,
        "id": f"gmaps-place-{org}-{candidate.get('place_id') or digest[:16]}",
        "signal_type": "place_summary",
        "source_class": "public_business_listing",
        "evidence_span": evidence,
        "metrics": {
            "title": candidate.get("title"),
            "address": candidate.get("address"),
            "phone": candidate.get("phone"),
            "website": candidate.get("web_site"),
            "place_id": candidate.get("place_id"),
            "data_id": candidate.get("data_id"),
            "latitude": candidate.get("latitude"),
            "longitude": candidate.get("longitude", candidate.get("longtitude")),
        },
        "strategy": "places_identity_resolution",
    }]
    if candidate.get("web_site"):
        observations.append({
            **common,
            "id": f"gmaps-company-profile-{org}-{candidate.get('place_id') or digest[:16]}",
            "signal_type": "company_profile",
            "source_class": "public_business_listing",
            "evidence_span": evidence,
            "metrics": {
                "official_website_candidate": candidate.get("web_site"),
                "title": candidate.get("title"),
                "place_id": candidate.get("place_id"),
            },
            "strategy": "company_site_identity",
        })
    rating = float(candidate.get("review_rating") or 0)
    count = int(candidate.get("review_count") or 0)
    if count > 0 and 0 < rating <= 5:
        observations.append({
            **common,
            "id": f"gmaps-review-summary-{org}-{candidate.get('place_id') or digest[:16]}",
            "signal_type": "review_summary",
            "source_class": "customer_review_summary",
            "evidence_span": evidence,
            "metrics": {
                "rating": rating,
                "rating_scale": 5,
                "review_count": count,
                "reviews_per_rating": candidate.get("reviews_per_rating") or {},
                "place_id": candidate.get("place_id"),
            },
            "strategy": "places_rating_reviews",
        })
        observations.append({
            **common,
            "id": f"gmaps-profile-metrics-{org}-{candidate.get('place_id') or digest[:16]}",
            "signal_type": "profile_metrics",
            "source_class": "public_business_listing",
            "evidence_span": evidence,
            "metrics": {
                "rating": rating,
                "rating_scale": 5,
                "review_count": count,
                "place_id": candidate.get("place_id"),
            },
            "strategy": "social_profile_metrics",
        })
        observations.append({
            **common,
            "id": f"gmaps-buzz-{org}-{candidate.get('place_id') or digest[:16]}",
            "signal_type": "buzz_metrics",
            "source_class": "customer_review_summary",
            "evidence_span": evidence,
            "metrics": {
                "review_count": count,
                "rating": rating,
                "rating_scale": 5,
                "place_id": candidate.get("place_id"),
            },
            "strategy": "buzz_peer_normalization",
        })
    for index, review in enumerate(candidate.get("user_reviews") or []):
        star = float(review.get("rating_float") or review.get("Rating") or 0)
        if not 0 < star <= 5:
            continue
        review_id = str(review.get("review_id") or hashlib.sha256(json.dumps(review, sort_keys=True).encode()).hexdigest()[:20])
        text = str(review.get("text_original") or review.get("Description") or "").strip()
        observations.append({
            **common,
            "id": f"gmaps-review-{org}-{review_id}",
            "signal_type": "review",
            "source_class": "customer_review",
            "evidence_span": text[:1200] if text else f"Explicit customer rating: {star}/5",
            "published_at": review.get("published_at"),
            "reviewer_id": str(review.get("author_url") or review.get("Name") or f"anonymous-{index}"),
            "metrics": {"rating": star, "rating_scale": 5, "review_id": review_id},
            "sentiment_label": review_label(star),
            "sentiment_model_version": "explicit_star_rating_v1",
            "strategy": "independent_sentiment",
        })
    return observations, {
        "status": "exact_match",
        "candidates": len(candidates),
        "title": candidate.get("title"),
        "review_count": count,
        "review_rating": rating,
        "assessment": assessment,
        "place_id": candidate.get("place_id"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Identity-gate and normalize Google Maps scraper JSONL.")
    parser.add_argument("--profiles", required=True)
    parser.add_argument("--organisations", required=True)
    parser.add_argument("--raw-results", nargs="+", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()

    wanted = [line.strip() for line in Path(args.organisations).read_text().splitlines() if line.strip()]
    profiles = {str(row["organisation_number"]): row for row in read_jsonl(Path(args.profiles))}
    raw = [item for source in args.raw_results for item in read_jsonl(Path(source))]
    by_org: dict[str, list[dict]] = defaultdict(list)
    for row in raw:
        by_org[str(row.get("input_id") or "")].append(row)
    retrieved_at = utc_now()
    observations: list[dict] = []
    company_results = []
    for org in wanted:
        company_observations, result = normalize_company(profiles[org], by_org.get(org, []), retrieved_at)
        observations.extend(company_observations)
        company_results.append({"organisation_number": org, **result})
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in observations), encoding="utf-8")
    statuses = defaultdict(int)
    for item in company_results:
        statuses[item["status"]] += 1
    report = {
        "connector": "google_maps_unofficial_crawler_identity_gate_v1",
        "companies": len(wanted),
        "raw_results": len(raw),
        "exact_matches": statuses["exact_match"],
        "companies_with_ratings": sum(item.get("review_count", 0) > 0 for item in company_results),
        "review_observations": sum(item.get("signal_type") == "review" for item in observations),
        "observations": len(observations),
        "status_counts": dict(statuses),
        "company_results": company_results,
        "claim_boundary": "Technically verified experimental output from an unofficial Google Maps crawler; terms review remains required.",
    }
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "company_results"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
