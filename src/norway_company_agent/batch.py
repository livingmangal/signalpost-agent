from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from .evidence import evidence, utc_now
from .official import accounting_obligation_assessment
from .sampling import iter_bulk


TERMINAL_STATES = {
    "complete",
    "not_applicable",
    "not_found",
    "blocked_policy",
    "blocked_robots",
    "source_error",
    "budget_exhausted",
    "submission_error",
}


def read_organisation_inputs(path: str | Path) -> list[dict[str, Any]]:
    source = Path(path)
    text = source.read_text(encoding="utf-8")
    values: list[Any]
    if source.suffix == ".json":
        body = json.loads(text)
        values = body if isinstance(body, list) else body.get("organisation_numbers", [])
    elif source.suffix == ".jsonl":
        values = [json.loads(line) for line in text.splitlines() if line.strip()]
    else:
        values = [line.strip() for line in text.splitlines() if line.strip()]
    records = []
    for value in values:
        org = value.get("organisation_number") if isinstance(value, dict) else value
        org = "".join(character for character in str(org or "") if character.isdigit())
        if len(org) != 9:
            raise ValueError(f"Invalid Norwegian organisation number: {value!r}")
        record = {"organisation_number": org}
        if isinstance(value, dict):
            for key in ("evaluation_split", "sample_slice"):
                if value.get(key) is not None:
                    record[key] = value[key]
        records.append(record)
    orgs = [record["organisation_number"] for record in records]
    if len(orgs) != len(set(orgs)):
        raise ValueError("Organisation-number input contains duplicates")
    return records


def read_organisation_numbers(path: str | Path) -> list[str]:
    return [record["organisation_number"] for record in read_organisation_inputs(path)]


def profiles_from_bulk(path: str | Path, organisation_numbers: Iterable[str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    requested = list(organisation_numbers)
    wanted = set(requested)
    snapshot_sha256 = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    retrieved_at = utc_now()
    found: dict[str, dict[str, Any]] = {}
    scanned = 0
    for profile in iter_bulk(path):
        scanned += 1
        org = profile["organisation_number"]
        if org not in wanted:
            continue
        raw = profile.pop("raw", {})
        profile["evidence"] = {
            "registry": evidence(
                "registry",
                "available",
                "official_registry_bulk",
                "https://data.brreg.no/enhetsregisteret/api/enheter/lastned/csv",
                value=raw,
                retrieved_at=retrieved_at,
                content_sha256=snapshot_sha256,
                source_row_key=org,
            ),
            "accounting_obligation": accounting_obligation_assessment(profile),
        }
        found[org] = profile
        if len(found) == len(wanted):
            break
    missing = [org for org in requested if org not in found]
    if missing:
        raise ValueError(f"Organisation numbers absent from registry snapshot: {missing[:10]}")
    return [found[org] for org in requested], {
        "registry_snapshot_sha256": snapshot_sha256,
        "registry_rows_scanned": scanned,
        "requested": len(requested),
        "selected": len(found),
    }


def evidence_terminal_state(record: dict[str, Any] | None) -> str:
    if not record:
        return "submission_error"
    status = record.get("status")
    if status == "available":
        return "complete"
    if status == "not_applicable":
        return "not_applicable"
    if status == "not_found":
        return "not_found"
    if status == "not_available":
        return "not_found"
    if status == "blocked":
        note = str(record.get("note") or "").casefold()
        return "blocked_robots" if "robot" in note else "blocked_policy"
    if status == "source_error":
        return "source_error"
    if status == "failed":
        return "source_error"
    if status == "ambiguous":
        return "complete"
    return "submission_error"


def terminal_envelope(
    profile: dict[str, Any],
    *,
    run_id: str,
    modules: Iterable[str],
    started_at: str,
    completed_at: str,
) -> dict[str, Any]:
    module_states = {}
    for module in modules:
        record = profile.get("evidence", {}).get(module)
        module_states[module] = {
            "state": evidence_terminal_state(record),
            "retry_count": int((record or {}).get("retry_count") or 0),
            "final_timestamp": (record or {}).get("retrieved_at") or completed_at,
        }
    entity_state = "submission_error" if any(item["state"] == "submission_error" for item in module_states.values()) else "complete"
    return {
        "run_id": run_id,
        "organisation_number": profile["organisation_number"],
        "state": entity_state,
        "started_at": started_at,
        "completed_at": completed_at,
        "modules": module_states,
        "profile": profile,
    }


def profile_to_contract_envelope(
    profile: dict[str, Any],
    *,
    run_id: str,
    started_at: str,
    completed_at: str,
    operations: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a minimal terminal envelope conforming to OUTPUT_CONTRACT.md schema."""
    org = profile["organisation_number"]
    evidence_list: list[dict[str, Any]] = []
    claims_list: list[dict[str, Any]] = []
    ev_counter = 0

    evidence_dict = profile.get("evidence", {})

    def add_claim(field: str, value: Any, ev_record: dict[str, Any] | None, default_url: str = "") -> None:
        nonlocal ev_counter
        if not ev_record:
            claims_list.append({
                "field": field,
                "value": None,
                "availability": "not_available",
                "confidence": 1.0,
                "evidence_ids": [],
            })
            return

        status = ev_record.get("status", "not_available")
        availability = status if status in ("available", "not_available", "blocked", "not_applicable", "ambiguous", "failed") else "failed"

        # If value is empty/None, mark availability as not_available
        if value is None or (isinstance(value, str) and not value.strip()) or (isinstance(value, (list, dict)) and len(value) == 0):
            if availability == "available":
                availability = "not_available"
            value = None

        ev_counter += 1
        ev_id = f"ev-{org}-{ev_counter}"

        ev_item = {
            "id": ev_id,
            "source_url": ev_record.get("source_url") or default_url or "https://data.brreg.no",
            "source_class": ev_record.get("source_class") or "official_registry",
            "retrieved_at": ev_record.get("retrieved_at") or completed_at,
            "content_sha256": ev_record.get("content_sha256") or ("0" * 64),
            "claim_span": f"{field}: {str(value)[:100]}" if value is not None else ev_record.get("note", f"{field} checked"),
        }
        evidence_list.append(ev_item)

        claims_list.append({
            "field": field,
            "value": value if availability == "available" else None,
            "availability": availability,
            "confidence": 1.0 if availability == "available" else 0.8,
            "evidence_ids": [ev_id],
        })

    # 1. Official registry claims
    reg_ev = evidence_dict.get("registry")
    reg_val = (reg_ev or {}).get("value") or {}
    reg_url = "https://data.brreg.no/enhetsregisteret/api/enheter/lastned/csv"
    add_claim("company_name", reg_val.get("navn") or profile.get("name"), reg_ev, reg_url)

    legal_form = profile.get("legal_form") or reg_val.get("organisasjonsform.kode") or reg_val.get("organisasjonsform")
    add_claim("legal_form", legal_form, reg_ev, reg_url)

    ind_code = profile.get("industry_code") or reg_val.get("naeringskode1.kode") or reg_val.get("naeringskode1")
    ind_label = profile.get("industry_label") or reg_val.get("naeringskode1.beskrivelse") or ""
    nace_str = f"{ind_code} - {ind_label}".strip(" -") if ind_code or ind_label else None
    add_claim("nace_industry", nace_str, reg_ev, reg_url)

    addr_parts = [
        reg_val.get("forretningsadresse.adresse") or reg_val.get("postadresse.adresse"),
        reg_val.get("forretningsadresse.postnummer") or reg_val.get("postadresse.postnummer"),
        reg_val.get("forretningsadresse.poststed") or reg_val.get("postadresse.poststed"),
        reg_val.get("forretningsadresse.kommune") or profile.get("municipality"),
    ]
    addr_str = ", ".join(str(p).strip() for p in addr_parts if p and str(p).strip()) or None
    add_claim("registered_office", addr_str, reg_ev, reg_url)

    reg_date = reg_val.get("registreringsdatoenhetsregisteret") or reg_val.get("stiftelsesdato") or profile.get("registration_date")
    add_claim("registration_date", reg_date, reg_ev, reg_url)

    emp_count = profile.get("employees")
    if emp_count is None and reg_val.get("antallAnsatte") is not None and str(reg_val.get("antallAnsatte")).strip():
        try:
            emp_count = int(reg_val.get("antallAnsatte"))
        except (ValueError, TypeError):
            emp_count = None
    add_claim("employee_count", emp_count, reg_ev, reg_url)

    # 2. Website claim
    web_ev = evidence_dict.get("website")
    web_val = (web_ev or {}).get("value") or {}
    add_claim("official_website", web_val.get("canonical_domain") or profile.get("website"), web_ev, str(profile.get("website") or ""))

    # 3. Financial claims
    fin_ev = evidence_dict.get("financials")
    fin_records = ((fin_ev or {}).get("value") or {}).get("records") or []
    latest_fin = fin_records[0] if fin_records else {}
    add_claim("revenue", latest_fin.get("revenue"), fin_ev, f"https://data.brreg.no/regnskapsregisteret/regnskap/{org}")
    add_claim("operating_result", latest_fin.get("operating_result"), fin_ev, f"https://data.brreg.no/regnskapsregisteret/regnskap/{org}")
    add_claim("equity", latest_fin.get("equity"), fin_ev, f"https://data.brreg.no/regnskapsregisteret/regnskap/{org}")

    def _val(mod: str) -> dict[str, Any]:
        v = (evidence_dict.get(mod) or {}).get("value")
        return v if isinstance(v, dict) else {}

    # 4. Roles
    roles_ev = evidence_dict.get("roles")
    roles_list = _val("roles").get("roles") or []
    roles_url = f"https://data.brreg.no/enhetsregisteret/api/enheter/{org}/roller"
    ceo_name = next((r.get("name") for r in roles_list if "daglig leder" in str(r.get("role") or "").lower()), None)
    add_claim("ceo", ceo_name, roles_ev, roles_url)

    chair_name = next((r.get("name") for r in roles_list if r.get("role_code") == "LEDE" or ("leder" in str(r.get("role") or "").lower() and "daglig" not in str(r.get("role") or "").lower())), None)
    add_claim("board_chair", chair_name, roles_ev, roles_url)

    board_members = [r.get("name") for r in roles_list if r.get("group_code") == "STYR" and not r.get("inactive") and r.get("name")]
    add_claim("board_members", ", ".join(board_members) if board_members else None, roles_ev, roles_url)

    # 5. Locations / Subunits
    loc_ev = evidence_dict.get("locations")
    loc_list = _val("locations").get("locations") or []
    subunits_count = len(loc_list) if loc_list else (_val("locations").get("count") or 0)
    add_claim("subunits_count", subunits_count, loc_ev, f"https://data.brreg.no/enhetsregisteret/api/underenheter?overordnetEnhet={org}")

    # 6. Footprint
    jobs_count = _val("jobs").get("count", 0)
    add_claim("jobs", jobs_count if jobs_count > 0 else None, evidence_dict.get("jobs"))

    news_count = _val("news_activity").get("count", 0)
    add_claim("news_activity", news_count if news_count > 0 else None, evidence_dict.get("news_activity"))

    add_claim("profile_summary", _val("profile_summary").get("summary"), evidence_dict.get("profile_summary"))

    ops = operations or {}
    return {
        "organisation_number": org,
        "run": {
            "run_id": run_id,
            "started_at": started_at,
            "completed_at": completed_at,
            "terminal_status": "completed",
        },
        "claims": claims_list,
        "evidence": evidence_list,
        "changes": profile.get("changes", []),
        "errors": profile.get("errors", []),
        "operations": {
            "requests": ops.get("requests", 0),
            "runtime_ms": ops.get("elapsed_ms") or ops.get("runtime_ms", 0),
            "third_party_cost_usd": 0.0,
        },
    }


def validate_envelopes(envelopes: list[dict[str, Any]], expected_count: int) -> dict[str, Any]:
    orgs = [item.get("organisation_number") for item in envelopes]
    invalid_states = [
        {"organisation_number": item.get("organisation_number"), "state": state.get("state")}
        for item in envelopes
        for state in item.get("modules", {}).values()
        if state.get("state") not in TERMINAL_STATES
    ]
    schema_errors = []
    try:
        from .models import validate_batch_envelope
        for envelope in envelopes:
            try:
                validate_batch_envelope(envelope)
            except Exception as exc:
                schema_errors.append({
                    "organisation_number": envelope.get("organisation_number"),
                    "error": str(exc),
                })
    except Exception as exc:
        schema_errors.append({"error": str(exc)})

    checks = {
        "exact_expected_count": len(envelopes) == expected_count,
        "unique_organisation_numbers": len(orgs) == len(set(orgs)),
        "all_entity_states_terminal": all(item.get("state") in TERMINAL_STATES for item in envelopes),
        "all_module_states_terminal": not invalid_states,
        "zero_silent_drops": len(envelopes) == expected_count and len(orgs) == len(set(orgs)),
        "schema_valid": not schema_errors,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "invalid_states": invalid_states,
        "schema_errors": schema_errors,
    }


def profile_complete_for_modules(profile: dict[str, Any], modules: Iterable[str]) -> bool:
    records = profile.get("evidence", {})
    return all(module in records and records[module].get("status") != "not_fetched" for module in modules)
