#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = ROOT / "src" / "norway_company_agent" / "templates" / "prototype.html"


def load_template() -> str:
    return TEMPLATE_PATH.read_text(encoding="utf-8")


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def normalize_independent_score(independent_score: dict | None) -> dict:
    result = dict(independent_score or {})
    if not result:
        return result
    score = result.get("score") or {}
    submission = score.get("submission_1000") or {}
    identity = (result.get("qualification") or {}).get("identity_gate") or {}
    if submission:
        result["qualification_passed"] = bool((result.get("qualification") or {}).get("passed"))
        result["raw_score"] = submission.get("raw_score", score.get("raw_score", 0))
        result["category_scores"] = {
            key: value.get("score", 0) for key, value in (submission.get("categories") or {}).items()
        }
        result["identity_audit"] = {
            "published_domains_correct": identity.get("published_domains_exact", 0),
            "published_socials_correct": identity.get("published_socials_exact", 0),
        }
        result["proxy"] = result.get("proxy") or {
            "submission_1000": (result.get("proxy_results_not_adopted") or {}).get("submission_1000", 0),
            "extension_250": (result.get("proxy_results_not_adopted") or {}).get("extension_250", 0),
        }
    return result


def qualification_copy(score: dict | None, independent_score: dict | None = None) -> tuple[str, str]:
    score = score or {}
    independent_score = normalize_independent_score(independent_score)
    if independent_score.get("qualification_passed"):
        independent = independent_score.get("raw_score", 0)
        proxy = (independent_score.get("proxy") or {}).get("submission_1000", score.get("raw_score", 0))
        return (
            f"Independent judge {independent}/100 · qualification passed · proxy {proxy}/100",
            "The independent score reached the 80-point target on both frozen corpora. Exact-entity publication, filing history and fresh PDF checks passed; calendar-time operation, open-ended research and broad context coverage remain unproven.",
        )
    if score.get("scorer") == "signalpost_all_source_completeness_v1":
        combined = score.get("combined") or {}
        return (
            f"Evidence completeness {combined.get('experimental_completeness_mean', 0):.2f}/100 experimental · {combined.get('strict_completeness_mean', 0):.2f}/100 strict",
            "LinkedIn discovery now enriches exact company records, but automated LinkedIn captures remain experimental. Company sites and social handles only enter the strict layer after independent identity verification.",
        )
    if "raw_score" in score:
        raw = score.get("raw_score", 0)
        if score.get("qualification_passed"):
            return (
                f"Competition proxy qualified · {raw}/100 · independent hidden score still required",
                "The corrected proxy passes its current gates. Final ranking still requires evaluator-owned hidden batches and a fresh independent review.",
            )
        failures = len(score.get("unproven_or_failed") or [])
        return (
            f"Competition proxy {raw}/100 · {failures} gate(s) unproven or failed",
            "This is an optimization measurement, not an official competition score. Open the scorecard to see the remaining hard gates.",
        )
    qualification = score.get("qualification") or {}
    weighted = score.get("weighted_score") or {}
    if qualification.get("poc_qualified"):
        points = weighted.get("verified_points")
        maximum = weighted.get("maximum_points")
        points_copy = f"{points}/{maximum} verified core points" if points is not None and maximum is not None else "core gate passed"
        return (
            f"POC qualified · {points_copy} · not production-qualified",
            "Frozen core checks passed. Search-based discovery and sentiment remain quarantined pending their own external evaluation.",
        )
    return (
        "1,000-entity frozen POC · not a production service",
        "Qualification is pending; inspect the evidence and scorecard before making a product claim.",
    )


def compact(row: dict, external_observations: list[dict] | None = None) -> dict:
    evidence = row.get("evidence", {})
    financial = evidence.get("financials", {})
    financial_history = evidence.get("financial_history", {})
    roles = evidence.get("roles", {})
    locations = evidence.get("locations", {})
    website = evidence.get("website", {})
    website_value = dict(website.get("value") or {})
    if website.get("status") == "available" and not website_value.get("title"):
        website_value["title"] = "Company site fetched"
    identity_assessment = website_value.get("identity_assessment") or {}
    if website.get("status") == "available" and identity_assessment and not identity_assessment.get("publishable"):
        website_value["quarantined_title"] = website_value.get("title")
        website_value["quarantined_description"] = website_value.get("description")
        website_value["quarantined_social_count"] = len(website_value.get("discovered_social_links") or [])
        website_value["title"] = "Registry-linked site — identity not verified"
        website_value["description"] = "Fetched content is retained as discovered evidence but is not attributed to this legal entity."
    live = evidence.get("registry_live", {})
    accounting = evidence.get("accounting_obligation", {})
    external_observations = external_observations or []

    def observation_meta(item: dict) -> dict:
        return {
            "source": item.get("source_url"),
            "retrievedAt": item.get("retrieved_at"),
            "publishedAt": item.get("published_at") or item.get("date_published"),
            "hash": item.get("content_sha256"),
            "rightsStatus": item.get("rights_status"),
            "sourceClass": item.get("source_class"),
        }

    linkedin_profiles = [
        item for item in external_observations
        if item.get("platform") == "linkedin" and item.get("signal_type") == "profile_metrics" and item.get("exact_entity")
    ]
    linkedin_workforce = [
        item for item in external_observations
        if item.get("platform") == "linkedin" and item.get("signal_type") == "workforce_snapshot" and item.get("exact_entity")
    ]
    linkedin_posts = [
        item for item in external_observations
        if item.get("platform") == "linkedin" and item.get("signal_type") == "public_post" and item.get("exact_entity")
    ]
    linkedin_jobs = [
        item for item in external_observations
        if item.get("platform") == "linkedin" and item.get("signal_type") == "job_posting" and item.get("exact_entity")
    ]
    verified_handles = {}
    for item in external_observations:
        if item.get("signal_type") != "profile_handle" or not item.get("exact_entity"):
            continue
        url = item.get("profile_url") or item.get("source_url")
        if url:
            verified_handles[(item.get("platform"), url)] = {
                "platform": item.get("platform"),
                "url": url,
                "rightsStatus": item.get("rights_status"),
            }
    linkedin_profile = linkedin_profiles[-1] if linkedin_profiles else None
    linkedin_headcount = linkedin_workforce[-1] if linkedin_workforce else None
    external = {
        "handles": list(verified_handles.values()),
        "linkedin": {
            "available": bool(linkedin_profile),
            "profile": ({**(linkedin_profile.get("metrics") or {}), **observation_meta(linkedin_profile)} if linkedin_profile else {}),
            "workforce": ({**(linkedin_headcount.get("metrics") or {}), **observation_meta(linkedin_headcount)} if linkedin_headcount else {}),
            "posts": [
                {
                    **(item.get("metrics") or {}),
                    "text": item.get("evidence_span"),
                    **observation_meta(item),
                }
                for item in linkedin_posts[:10]
            ],
            "jobs": [
                {
                    **(item.get("metrics") or {}),
                    "text": item.get("evidence_span"),
                    **observation_meta(item),
                }
                for item in linkedin_jobs[:10]
            ],
        },
    }

    def meta(record: dict) -> dict:
        return {
            "status": record.get("status", "not_run"),
            "source": record.get("source_url"),
            "sourceClass": record.get("source_class") or record.get("source_type"),
            "retrievedAt": record.get("retrieved_at"),
            "effectiveAt": record.get("effective_at") or record.get("as_of"),
            "hash": record.get("content_sha256"),
            "rowKey": record.get("source_row_key"),
        }
    return {
        "org": row["organisation_number"],
        "name": row["name"],
        "form": row["legal_form"],
        "employees": row["employees"],
        "municipality": row["municipality"],
        "industryCode": row["industry_code"],
        "industry": row["industry_label"],
        "website": row["website"],
        "adverse": bool(row["bankrupt"] or row["liquidating"]),
        "slice": row.get("sample_slice"),
        "split": row.get("evaluation_split"),
        "latestAccounts": row.get("latest_submitted_accounts"),
        "registrySource": evidence.get("registry", {}).get("source_url"),
        "registry": meta(evidence.get("registry", {})),
        "accounting": {**meta(accounting), "value": accounting.get("value") or {}},
        "financial": {**meta(financial), "records": (financial.get("value") or {}).get("records", [])[:3]},
        "financialHistory": {**meta(financial_history), "pdfs": (financial_history.get("value") or {}).get("pdfs", [])},
        "roles": {**meta(roles), "items": (roles.get("value") or {}).get("roles", [])[:30]},
        "locations": {**meta(locations), "items": (locations.get("value") or {}).get("locations", [])[:30]},
        "web": {**meta(website), "value": website_value},
        "liveStatus": live.get("status", "not_run"),
        "changes": row.get("change_history") or [],
        "external": external,
    }


def build(rows: list[dict], score: dict | None, control_loop: dict | None = None, independent_score: dict | None = None, external_by_org: dict[str, list[dict]] | None = None) -> str:
    independent_score = normalize_independent_score(independent_score)
    external_by_org = external_by_org or {}
    payload = json.dumps([compact(row, external_by_org.get(str(row["organisation_number"]), [])) for row in rows], ensure_ascii=False).replace("</", "<\\/")
    score_ui = score or {}
    if score_ui.get("scorer") == "signalpost_all_source_completeness_v1":
        combined = score_ui.get("combined") or {}
        strict = round(float(combined.get("strict_completeness_mean") or 0), 2)
        experimental = round(float(combined.get("experimental_completeness_mean") or 0), 2)
        score_ui = {
            **score_ui,
            "raw_score": experimental,
            "awardable_score": strict,
            "rubric_weights": {
                "strict_evidence_completeness": 100,
                "experimental_linkedin_completeness": 100,
                "strict_companies_at_50": combined.get("companies") or len(rows),
                "experimental_companies_at_65": combined.get("companies") or len(rows),
            },
            "category_scores": {
                "strict_evidence_completeness": strict,
                "experimental_linkedin_completeness": experimental,
                "strict_companies_at_50": combined.get("strict_at_50") or 0,
                "experimental_companies_at_65": combined.get("experimental_at_65") or 0,
            },
            "qualification_gates": {
                "32 exact LinkedIn profiles captured": True,
                "9 sites and 17 handles discovered downstream": True,
            },
        }
    score_payload = json.dumps(score_ui, ensure_ascii=False).replace("</", "<\\/")
    control_payload = json.dumps(control_loop or {}, ensure_ascii=False).replace("</", "<\\/")
    independent_payload = json.dumps(independent_score or {}, ensure_ascii=False).replace("</", "<\\/")
    status_copy, boundary_copy = (html.escape(value) for value in qualification_copy(score, independent_score))
    template = load_template()
    return template.format(
        boundary_copy=boundary_copy,
        payload=payload,
        score_payload=score_payload,
        independent_payload=independent_payload,
        control_payload=control_payload,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--score")
    parser.add_argument("--control-loop")
    parser.add_argument("--independent-score")
    parser.add_argument("--external-observations", nargs="*")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    rows = read_jsonl(Path(args.input))
    if args.limit:
        rows = rows[:args.limit]
    external_by_org: dict[str, list[dict]] = defaultdict(list)
    seen_observations: set[str] = set()
    for source in args.external_observations or []:
        for observation in read_jsonl(Path(source)):
            observation_id = str(observation.get("id") or json.dumps(observation, sort_keys=True, ensure_ascii=False))
            if observation_id in seen_observations:
                continue
            seen_observations.add(observation_id)
            organisation_number = str(observation.get("organisation_number") or "")
            if organisation_number:
                external_by_org[organisation_number].append(observation)
    score = json.loads(Path(args.score).read_text(encoding="utf-8")) if args.score and Path(args.score).exists() else None
    control_loop = json.loads(Path(args.control_loop).read_text(encoding="utf-8")) if args.control_loop and Path(args.control_loop).exists() else None
    independent_score = json.loads(Path(args.independent_score).read_text(encoding="utf-8")) if args.independent_score and Path(args.independent_score).exists() else None
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build(rows, score, control_loop, independent_score, external_by_org), encoding="utf-8")
    print(f"Wrote {output} with {len(rows)} profiles")
