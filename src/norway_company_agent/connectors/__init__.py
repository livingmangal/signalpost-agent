"""Connectors and normalizers for external company signals."""
from .workforce import extract_candidate, needs_ocr
from .maps import candidate_score
from .reviews import extract_aggregate_rating, slug
from .linkedin import (
    canonical_company_url,
    parse_detail_company_urls,
    parse_job_cards,
    parse_typeahead,
    assess_profile_identity,
    extract_profile,
    legal_name_profile_url,
    discovery_identity,
    normalized_full_name,
    official_site_aliases,
    parse_exact_typeahead,
)

__all__ = [
    "extract_candidate",
    "needs_ocr",
    "candidate_score",
    "extract_aggregate_rating",
    "slug",
    "canonical_company_url",
    "parse_detail_company_urls",
    "parse_job_cards",
    "parse_typeahead",
    "assess_profile_identity",
    "extract_profile",
    "legal_name_profile_url",
    "discovery_identity",
    "normalized_full_name",
    "official_site_aliases",
    "parse_exact_typeahead",
]
