from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from norway_company_agent.external_footprint import publishable_observation
from norway_company_agent.external_control import development_score
from norway_company_agent.connectors.reviews import extract_aggregate_rating, slug
from scripts.score_company_completeness import ENRICHMENT_WEIGHTS, FOUNDATION_WEIGHTS, score_rows, summarize
from scripts.extract_company_site_activity import observation as site_activity_observation
from scripts.extract_company_site_news import observation as site_news_observation
from scripts.build_verified_observations import build as build_verified_observations
from scripts.run_google_news_rss_connector import exact_title_match


class CompletenessScoreTests(unittest.TestCase):
    def test_all_source_weights_sum_to_one_hundred(self):
        self.assertEqual(sum(FOUNDATION_WEIGHTS.values()) + sum(ENRICHMENT_WEIGHTS.values()), 100.0)

    def test_all_source_score_combines_foundation_and_external_without_imputing_missing(self):
        profile = {
            "organisation_number": "923609016",
            "evidence": {
                "registry_live": {"status": "available", "value": {"organisation_number": "923609016"}},
                "financials": {"status": "available"},
                "roles": {"status": "available"},
                "locations": {"status": "available"},
                "website": {"status": "not_found"},
            },
        }
        components = {
            "exact_external_identity": 20,
            "verified_handles": 15,
            "profile_metrics": 10,
            "places_identity": 5,
            "places_reviews": 10,
            "workforce_jobs": 10,
            "public_buzz": 10,
            "independent_sentiment": 0,
            "freshness_evidence": 5,
        }
        result = {"organisation_number": "923609016", "company_name": "Example AS", "final": {"components": components, "experimental_components": components}}
        scored = score_rows([profile], [result])
        self.assertEqual(scored[0]["foundation_score"], 30.0)
        self.assertEqual(scored[0]["strict_enrichment"]["independent_sentiment"], 0.0)
        self.assertEqual(scored[0]["strict_completeness_score"], 88.0)
        self.assertEqual(summarize(scored)["companies"], 1)

    def test_site_activity_requires_exact_identity_and_preserves_snapshot_provenance(self):
        profile = {
            "organisation_number": "923609016",
            "evidence": {"website": {
                "status": "available",
                "source_url": "https://example.test/",
                "retrieved_at": "2026-08-23T00:00:00Z",
                "value": {
                    "final_url": "https://example.test/",
                    "content_sha256": "a" * 64,
                    "identity_assessment": {"publishable": True, "status": "exact", "score": 1.0},
                    "pages": [{"url": "https://example.test/"}],
                },
            }},
        }
        item = site_activity_observation(profile)
        self.assertIsNotNone(item)
        self.assertEqual(item["strategy"], "company_site_activity")
        self.assertTrue(publishable_observation(item))
        profile["evidence"]["website"]["value"]["identity_assessment"]["publishable"] = False
        self.assertIsNone(site_activity_observation(profile))

    def test_news_title_gate_requires_the_full_legal_name_core(self):
        self.assertTrue(exact_title_match("NORDIC DOOR AS", "Nordic Door AS åpner ny fabrikk - Lokalavisa"))
        self.assertFalse(exact_title_match("NORDIC DOOR AS", "Nordic investors prefer another door - Example"))
        self.assertTrue(exact_title_match("SOLVANG ASA", "Sterkt årsresultat fra Solvang ASA i 2024 - Skipsrevyen"))
        self.assertFalse(exact_title_match("VIND HOLDING AS", "Inntektene til Aneo Roan Vind Holding AS stupte - mn24.no"))
        self.assertFalse(exact_title_match("CONSTO AS", "Drastisk fall hos Consto Bergen AS - BT"))

    def test_site_news_requires_exact_identity_and_a_captured_news_path(self):
        profile = {
            "organisation_number": "923609016",
            "evidence": {"website": {
                "status": "available", "retrieved_at": "2026-08-23T00:00:00Z",
                "value": {
                    "identity_assessment": {"publishable": True, "score": 1.0},
                    "pages": [{"url": "https://example.test/aktuelt/new-contract", "title": "New contract", "content_sha256": "a" * 64}],
                },
            }},
        }
        item = site_news_observation(profile)
        self.assertEqual(item["signal_type"], "public_post")
        self.assertTrue(publishable_observation(item))
        profile["evidence"]["website"]["value"]["pages"][0]["url"] = "https://example.test/contact"
        self.assertIsNone(site_news_observation(profile))

    def test_verified_observations_require_known_org_and_snapshot_hash(self):
        profiles = [{"organisation_number": "923609016", "name": "Example AS"}]
        seed = {"organisation_number": "923609016", "platform": "news", "signal_type": "public_mention", "source_url": "https://example.test/news", "content_sha256": "a" * 64, "evidence_span": "Example AS", "proof": "Exact legal name"}
        self.assertTrue(build_verified_observations([seed], profiles)[0]["exact_entity"])
        seed["content_sha256"] = "bad"
        with self.assertRaises(ValueError):
            build_verified_observations([seed], profiles)

    def test_directory_identity_is_experimental_and_never_becomes_strict(self):
        item = {
            "id": "directory-1", "organisation_number": "923609016", "platform": "company_directory",
            "signal_type": "company_profile", "source_url": "https://example.test/923609016",
            "retrieved_at": "2026-08-23T00:00:00Z", "content_sha256": "a" * 64,
            "exact_entity": True, "identity_proof": [{"type": "organisation_number", "value": "923609016"}],
            "acquisition_mode": "rights_review_experiment", "rights_status": "review_required",
            "source_class": "public_company_directory", "strategy": "company_directory_identity",
        }
        profile = {"organisation_number": "923609016", "name": "Example AS", "evidence": {}}
        score = development_score(profile, [item])
        self.assertEqual(score["components"]["exact_external_identity"], 0.0)
        self.assertEqual(score["experimental_components"]["exact_external_identity"], 20.0)
        self.assertFalse(publishable_observation(item))

    def test_fagfolk_rating_parser_uses_jsonld_and_slug_is_stable(self):
        raw = b'<script type="application/ld+json">{"aggregateRating":{"ratingValue":4.4,"ratingCount":25}}</script>'
        self.assertEqual(extract_aggregate_rating(raw)[:2], (4.4, 25))
        self.assertEqual(slug("NORDIC DØR AS"), "nordic-dor-as")


if __name__ == "__main__":
    unittest.main()
