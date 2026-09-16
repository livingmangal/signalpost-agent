from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from norway_company_agent.external_footprint import aggregate_footprint, publishable_observation, validate_observation
from norway_company_agent.external_tasks import plan_external_tasks
from norway_company_agent.external_control import development_score, run_company_control, strategy_order
from norway_company_agent.discovery import score_search_candidate

# Canonical connector imports
from norway_company_agent.connectors.workforce import extract_candidate, needs_ocr
from norway_company_agent.connectors.maps import candidate_score
from norway_company_agent.connectors.linkedin import (
    canonical_company_url,
    parse_detail_company_urls,
    parse_job_cards,
    parse_typeahead,
    assess_profile_identity as assess_linkedin_profile_identity,
    extract_profile as extract_linkedin_profile,
    legal_name_profile_url,
    discovery_identity as linkedin_discovery_identity,
    normalized_full_name as linkedin_normalized_full_name,
    official_site_aliases as linkedin_official_site_aliases,
    parse_exact_typeahead as parse_linkedin_exact_typeahead,
)


class ExternalFootprintTests(unittest.TestCase):
    def observation(self, **changes):
        base = {
            "id": "obs-1",
            "organisation_number": "923609016",
            "platform": "google_places",
            "signal_type": "review",
            "source_url": "https://maps.google.com/example",
            "retrieved_at": "2026-08-20T00:00:00Z",
            "content_sha256": "a" * 64,
            "exact_entity": True,
            "identity_proof": [{"type": "address_match", "value": "Oslo"}],
            "acquisition_mode": "official_api",
            "rights_status": "approved",
            "source_class": "customer_review",
            "evidence_span": "Helpful staff",
        }
        return {**base, **changes}

    def test_publication_requires_rights_identity_hash_and_span(self):
        self.assertTrue(publishable_observation(self.observation()))
        bad = self.observation(exact_entity=False, content_sha256=None, evidence_span=None, rights_status="unknown")
        reasons = validate_observation(bad)
        self.assertIn("exact legal entity is not verified", reasons)
        self.assertIn("missing content hash", reasons)
        self.assertIn("missing evidence span", reasons)
        self.assertIn("source rights are not approved", reasons)

    def test_unofficial_scraper_output_is_experimental_not_publishable(self):
        item = self.observation(platform="linkedin", signal_type="job_posting", acquisition_mode="jobspy_experiment")
        self.assertFalse(publishable_observation(item))

    def test_linkedin_guest_jobs_require_exact_verified_company_url(self):
        raw = b'''<div class="base-search-card" data-entity-urn="urn:li:jobPosting:4456746433">
          <a class="base-card__full-link" href="https://no.linkedin.com/jobs/view/example-4456746433?x=1"></a>
          <span class="sr-only">Project manager</span>
          <h4 class="base-search-card__subtitle"><a href="https://no.linkedin.com/company/af-gruppen?trk=x">AF Gruppen</a></h4>
          <span class="job-search-card__location">Oslo</span><time datetime="2026-08-23"></time>
        </div>
        <div class="base-search-card" data-entity-urn="urn:li:jobPosting:4456746434">
          <a class="base-card__full-link" href="https://linkedin.com/jobs/view/other-4456746434"></a>
          <span class="sr-only">Wrong parent job</span>
          <h4 class="base-search-card__subtitle"><a href="https://linkedin.com/company/af-gruppen-sverige">AF Gruppen Sverige</a></h4>
        </div>'''
        jobs, candidates = parse_job_cards(raw, "https://linkedin.com/company/af-gruppen")
        self.assertEqual(candidates, 2)
        self.assertEqual([item["job_id"] for item in jobs], ["4456746433"])
        self.assertEqual(jobs[0]["company_url"], "https://linkedin.com/company/af-gruppen")

    def test_linkedin_company_urls_and_typeahead_are_normalized_without_claiming_ambiguous_ids(self):
        self.assertEqual(
            canonical_company_url("https://no.linkedin.com/company/Norsk-Fiskeeksport/about?trk=x"),
            "https://linkedin.com/company/norsk-fiskeeksport",
        )
        candidates = parse_typeahead(
            json.dumps([
                {"id": "34440", "type": "COMPANY", "displayName": "AF Gruppen"},
                {"id": "1188022", "type": "COMPANY", "displayName": "AF Gruppen Sverige"},
            ]).encode(),
            "AF GRUPPEN ASA",
        )
        self.assertTrue(candidates[0]["exact_legal_name_core"])
        self.assertFalse(candidates[1]["exact_legal_name_core"])
        self.assertEqual(
            parse_detail_company_urls(
                b'<a href="https://no.linkedin.com/company/af-gruppen?trk=job">AF Gruppen</a>'
                b'<a href="https://example.test/company/wrong">Wrong</a>'
            ),
            {"https://linkedin.com/company/af-gruppen"},
        )

    def test_linkedin_guest_profile_uses_structured_company_data_and_ignores_dormant_challenge_code(self):
        graph = {
            "@graph": [
                {
                    "@type": "DiscussionForumPosting",
                    "author": {"url": "https://no.linkedin.com/company/af-gruppen"},
                    "datePublished": "2026-08-21T06:15:05Z",
                    "text": "Exact company update",
                    "url": "https://no.linkedin.com/posts/example-activity-7496449781678927873-x",
                },
                {
                    "@type": "Organization",
                    "name": "AF Gruppen",
                    "url": "https://no.linkedin.com/company/af-gruppen",
                    "description": "Construction group",
                    "numberOfEmployees": {"value": 1303},
                },
            ]
        }
        raw = (
            '<meta name="description" content="AF Gruppen | 56 726 followers on LinkedIn">'
            f'<script type="application/ld+json">{json.dumps(graph)}</script>'
            '<script>const dormant="recaptcha/challengepage";</script>'
            '<div data-test-id="about-us__size"><dd>5,001-10,000 employees</dd></div>'
            '<article class="main-feed-activity-card" data-activity-urn="urn:li:activity:7496449781678927873">'
            '<a data-test-id="social-actions__reactions" data-num-reactions="29"></a>'
            '<a data-test-id="social-actions__comments" data-num-comments="4"></a></article>'
        ).encode()
        profile = extract_linkedin_profile(raw, "https://linkedin.com/company/af-gruppen")
        self.assertEqual(profile["followers"], 56726)
        self.assertEqual(profile["visible_employees"], 1303)
        self.assertEqual(profile["employee_size_label"], "5,001-10,000 employees")
        self.assertEqual(profile["posts"][0]["likes"], 29)
        self.assertEqual(profile["posts"][0]["comments"], 4)

    def test_linkedin_guest_profile_rejects_authwall_without_organization_data(self):
        with self.assertRaisesRegex(RuntimeError, "no structured organization"):
            extract_linkedin_profile(b'<script>recaptcha/challengepage</script>', "https://linkedin.com/company/example")

    def test_linkedin_stale_handle_fallback_is_bounded_to_registry_legal_name(self):
        self.assertEqual(legal_name_profile_url("DIPS AS"), "https://www.linkedin.com/company/dips-as")
        self.assertEqual(legal_name_profile_url("RØD & BLÅ AS"), "https://www.linkedin.com/company/rod-bla-as")

    def test_linkedin_discovery_requires_exact_typeahead_name_and_corroboration(self):
        raw = json.dumps([
            {"id": "1", "type": "COMPANY", "displayName": "DIPS AS"},
            {"id": "2", "type": "COMPANY", "displayName": "DIPS ASA"},
        ]).encode()
        self.assertEqual([item["linkedin_company_id"] for item in parse_linkedin_exact_typeahead(raw, "DIPS AS")], ["1"])
        self.assertEqual(linkedin_normalized_full_name("RØD & BLÅ AS"), "rød blå as")
        company = {
            "name": "DIPS AS",
            "municipality": "BODØ",
            "website": "https://dips.com",
            "evidence": {"website": {"status": "available", "value": {"final_url": "https://dips.com"}}},
        }
        exact = linkedin_discovery_identity(company, {"name": "DIPS AS", "website": "https://www.dips.com", "headquarters": "Bodø"}, {"legal_name_slug"})
        self.assertTrue(exact["exact_entity"])
        weak = linkedin_discovery_identity(company, {"name": "DIPS AS", "website": "https://unrelated.test", "headquarters": "Oslo"}, {"legal_name_slug"})
        self.assertFalse(weak["exact_entity"])

    def test_linkedin_fuzzy_discovery_uses_verified_site_alias_and_reverse_domain(self):
        company = {
            "name": "JARRE AS",
            "municipality": "INDRE ØSTFOLD",
            "website": "https://jarre.co",
            "evidence": {
                "website": {"status": "available", "value": {"final_url": "https://jarre.co", "title": "Jarre&Co"}},
                "roles": {"value": {"roles": [{"name": "Christian Jarre", "role_code": "DAGL"}]}},
            },
        }
        self.assertEqual(linkedin_official_site_aliases(company), ["Jarre&Co"])
        exact = linkedin_discovery_identity(
            company,
            {"name": "Jarre & Co", "website": "https://www.jarre.co", "headquarters": "Askim", "description": ""},
            {"official_site_alias:Jarre&Co"},
        )
        self.assertTrue(exact["exact_entity"])

    def test_linkedin_profile_identity_accepts_redirect_alias_only_with_name_or_reverse_domain_proof(self):
        profile = {
            "name": "ZAPTEC ASA",
            "website": "https://zaptec.com",
            "evidence": {"website": {"source_url": "https://www.zaptec.com/", "value": {"final_url": "https://www.zaptec.com/"}}},
        }
        accepted = assess_linkedin_profile_identity(
            profile,
            "https://linkedin.com/company/gozaptec",
            {"name": "Zaptec", "page_url": "https://linkedin.com/company/zaptec", "website": "https://www.zaptec.com"},
        )
        self.assertTrue(accepted["publishable_candidate"])
        rejected = assess_linkedin_profile_identity(
            profile,
            "https://linkedin.com/company/gozaptec",
            {"name": "Unrelated Parent", "page_url": "https://linkedin.com/company/unrelated", "website": "https://parent.test"},
        )
        self.assertFalse(rejected["publishable_candidate"])

    def test_google_play_observation_is_supported_but_unofficial_output_stays_experimental(self):
        item = self.observation(
            platform="google_play",
            signal_type="review_summary",
            acquisition_mode="unofficial_api_experiment",
            rights_status="review_required",
        )
        reasons = validate_observation(item)
        self.assertNotIn("unsupported platform", reasons)
        self.assertFalse(publishable_observation(item))

    def test_company_directory_is_not_a_website_discovery_candidate(self):
        profile = {"name": "OBLOMOV AS", "organisation_number": "991167315", "municipality": "SOLA"}
        result = {"url": "https://www.northdata.com/Oblomov-AS/BR-991167315", "title": "Oblomov AS", "snippet": "991167315", "rank": 1}
        assessment = score_search_candidate(profile, result)
        self.assertFalse(assessment["publishable_candidate"])
        self.assertEqual(assessment["status"], "rejected")

    def test_unknown_company_directory_with_org_number_is_not_a_candidate(self):
        profile = {"name": "AKSLA AS", "organisation_number": "923304290", "municipality": "ÅLESUND"}
        result = {"url": "https://vexter.no/selskap/aksla-as/923304290", "title": "AKSLA AS", "snippet": "923304290", "rank": 1}
        self.assertFalse(score_search_candidate(profile, result)["publishable_candidate"])

    def test_annual_workforce_parser_does_not_treat_norwegian_o_as_zero(self):
        heading = "Note 2 - Lonnskostnader, antall ansatte og lan til ansatte"
        self.assertEqual(extract_candidate(heading), (None, None, "no_employee_phrase", None))
        count, span, status, measure = extract_candidate("Det er to ansatte i sameiet.")
        self.assertEqual((count, status, measure), (2, "accepted", "employees"))
        self.assertEqual(span, "Det er to ansatte i sameiet.")
        self.assertEqual(extract_candidate("Selskapet har 1 2025 sysselsatt 2 arsverk.")[0], 2)
        self.assertEqual(extract_candidate("Antall arsverk syssetsatt i regnskapsaret: 3")[0], 3)
        self.assertEqual(extract_candidate("Stiftelsen har ingen ansatte og ingen arsverk.")[0], 0)
        self.assertEqual(extract_candidate("Selskapet hadde ingen ansatte i 2025.")[0], 0)
        self.assertEqual(extract_candidate("Gjennomsnittlig antall ansatte i regnskapsaret: 0")[0], 0)
        self.assertEqual(extract_candidate("Note Antall Aarsverk i regnskapsaret 0.00")[0], 0)
        self.assertEqual(extract_candidate("Tal pa Aarsverk i rekneskapsaret 1.50")[0], 1.5)
        self.assertTrue(needs_ocr("Digital cover text without the employee note"))
        self.assertFalse(needs_ocr("Selskapet har 2 ansatte. " + "Digital report text. " * 8))

    def test_aggregate_keeps_source_metrics_separate_and_abstains_on_thin_sentiment(self):
        items = [
            self.observation(id="a", sentiment_label="positive", sentiment_model_version="m1"),
            self.observation(id="b", platform="youtube", signal_type="profile_metrics", source_url="https://youtube.com/@example", evidence_span=None),
        ]
        result = aggregate_footprint(items, as_of="2026-08-22T00:00:00Z")
        self.assertEqual(result["accepted_observations"], 2)
        self.assertEqual(result["sentiment"]["status"], "abstain")
        self.assertNotIn("popularity_score", result)

    def test_customer_review_sentiment_accepts_ten_independent_reviewers_on_one_platform(self):
        items = [
            self.observation(
                id=f"review-{index}",
                sentiment_label="positive",
                sentiment_model_version="explicit_star_rating_v1",
                reviewer_id=f"reviewer-{index}",
            )
            for index in range(10)
        ]
        result = aggregate_footprint(items, as_of="2026-08-22T00:00:00Z")
        self.assertEqual(result["sentiment"]["status"], "available")
        self.assertEqual(result["sentiment"]["independent_reviewers"], 10)

    def test_google_maps_identity_gate_rejects_neighbor_and_accepts_exact_address(self):
        profile = {
            "organisation_number": "938702675",
            "name": "AF GRUPPEN ASA",
            "evidence": {
                "registry": {"value": {
                    "forretningsadresse.adresse": "Standardveien 1",
                    "forretningsadresse.postnummer": "0581",
                    "telefon": "22 89 11 00",
                }},
                "website": {"value": {
                    "final_url": "https://afgruppen.no/",
                    "identity_assessment": {"publishable": True},
                }},
            },
        }
        exact = candidate_score(profile, {
            "title": "AF Gruppen", "address": "Standardveien 1, 0581 Oslo, Norge",
            "phone": "+47 22 89 11 00", "web_site": "https://afgruppen.no/", "review_count": 21,
        })
        neighbor = candidate_score(profile, {
            "title": "AF Eiendom", "address": "Standardveien 1, 0581 Oslo, Norge",
            "phone": "+47 22 89 11 00", "web_site": "https://afgruppen.no/eiendom/", "review_count": 0,
        })
        self.assertTrue(exact["accepted"])
        self.assertFalse(neighbor["accepted"])

    def test_google_maps_exact_name_and_postcode_city_can_resolve_operating_address(self):
        profile = {
            "organisation_number": "999999999",
            "name": "EXAMPLE INDUSTRI AS",
            "evidence": {"registry": {"value": {
                "forretningsadresse.adresse": "c/o Accountant Other Street 1",
                "forretningsadresse.postnummer": "4021",
                "forretningsadresse.poststed": "STAVANGER",
            }}},
        }
        result = candidate_score(profile, {
            "title": "Example Industri AS", "address": "Factory Road 7, 4021 Stavanger, Norway",
            "phone": "", "web_site": "", "review_count": 4,
        })
        self.assertTrue(result["accepted"])
        self.assertTrue(result["postcode_city_match"])

    def test_google_maps_trade_name_requires_exact_address_phone_and_no_partial_name_collision(self):
        profile = {
            "name": "OSLOFJORDEN EIENDOMSMEGLING AS",
            "evidence": {"registry": {"value": {
                "forretningsadresse.adresse": "Stranden 81", "forretningsadresse.postnummer": "0250",
                "forretningsadresse.poststed": "Oslo", "telefon": "22620000",
            }}},
        }
        candidate = {"title": "PrivatMegleren Premium", "address": "Stranden 81, 0250 Oslo", "phone": "+47 22 62 00 00"}
        result = candidate_score(profile, candidate)
        self.assertFalse(result["trade_name_match"])
        self.assertFalse(result["accepted"])
        profile["organisation_number"] = "932083108"
        result = candidate_score(profile, candidate)
        self.assertTrue(result["trade_name_match"])
        self.assertTrue(result["accepted"])
        candidate["phone"] = "+47 99 99 99 99"
        self.assertFalse(candidate_score(profile, candidate)["accepted"])

    def test_experimental_maps_signals_raise_only_experimental_places_score(self):
        profile = {
            "organisation_number": "938702675",
            "name": "AF GRUPPEN ASA",
            "evidence": {"website": {"value": {"identity_assessment": {"publishable": False}}}},
        }
        common = {
            "organisation_number": "938702675",
            "platform": "google_places",
            "source_url": "https://www.google.com/maps/place/example",
            "retrieved_at": "2026-08-22T00:00:00Z",
            "content_sha256": "a" * 64,
            "exact_entity": True,
            "identity_proof": [{"type": "registry_address_match", "value": True}],
            "acquisition_mode": "unofficial_api_experiment",
            "rights_status": "review_required",
            "source_class": "public_business_listing",
            "evidence_span": "AF Gruppen; Standardveien 1; rating=2.5; reviews=21",
        }
        observations = [
            {**common, "id": "place", "signal_type": "place_summary", "strategy": "places_identity_resolution"},
            {**common, "id": "summary", "signal_type": "review_summary", "strategy": "places_rating_reviews"},
        ]
        score = development_score(profile, observations)
        self.assertEqual(score["score"], 0.0)
        self.assertEqual(score["experimental_potential_score"], 35.0)

    def test_aggregate_maps_rating_is_experimental_sentiment_and_buzz(self):
        profile = {
            "organisation_number": "938702675",
            "name": "AF GRUPPEN ASA",
            "evidence": {"website": {"value": {"identity_assessment": {"publishable": False}}}},
        }
        common = {
            "organisation_number": "938702675",
            "platform": "google_places",
            "source_url": "https://www.google.com/maps/place/example",
            "retrieved_at": "2026-08-22T00:00:00Z",
            "content_sha256": "a" * 64,
            "exact_entity": True,
            "identity_proof": [{"type": "registry_address_match", "value": True}],
            "acquisition_mode": "unofficial_api_experiment",
            "rights_status": "review_required",
            "evidence_span": "AF Gruppen; rating=4.4; reviews=21",
            "metrics": {"rating": 4.4, "rating_scale": 5, "review_count": 21},
        }
        observations = [
            {**common, "id": "summary", "signal_type": "review_summary", "strategy": "places_rating_reviews"},
            {**common, "id": "buzz", "signal_type": "buzz_metrics", "strategy": "buzz_peer_normalization"},
        ]
        score = development_score(profile, observations)
        self.assertEqual(score["score"], 0.0)
        self.assertEqual(score["experimental_sentiment_status"], "available")
        self.assertEqual(score["experimental_potential_score"], 35.0)

    def test_task_planner_uses_verified_handles_and_adds_core_connectors(self):
        profile = {
            "organisation_number": "923609016",
            "name": "Example AS",
            "evidence": {
                "website": {"value": {"social_links": [{"platform": "youtube", "url": "https://youtube.com/@example"}]}},
            },
        }
        tasks = plan_external_tasks(profile)
        connectors = {item["connector"] for item in tasks}
        self.assertIn("google_places_api", connectors)
        self.assertIn("jobs_provider", connectors)
        self.assertIn("youtube_connector", connectors)
        self.assertNotIn("permitted_search_api", connectors)

    def test_controller_recomputes_sentiment_and_records_marginal_gain(self):
        profile = {
            "organisation_number": "923609016",
            "name": "Example AS",
            "evidence": {"website": {"value": {"identity_assessment": {"publishable": True}}}},
        }
        handle = self.observation(signal_type="profile_handle", source_class="company_social", evidence_span=None, strategy="verified_handle_extraction")
        score = development_score(profile, [handle])
        self.assertGreater(score["score"], 0)
        self.assertEqual(score["sentiment_status"], "abstain")
        result = run_company_control(profile, [handle], minimum_iterations=10, maximum_iterations=15)
        self.assertGreaterEqual(result["iterations_run"], 10)
        self.assertTrue(any(item["score_delta"] > 0 for item in result["iterations"]))
        self.assertTrue(all("sentiment_status" in item for item in result["iterations"]))

    def test_controller_final_score_is_not_path_dependent_after_target_is_reached(self):
        profile = {
            "organisation_number": "923609016",
            "name": "Example AS",
            "evidence": {"website": {"value": {"identity_assessment": {"publishable": True}}}},
        }
        observations = [
            self.observation(signal_type="profile_handle", source_class="company_social", evidence_span=None, strategy="verified_handle_extraction"),
            self.observation(id="metric", platform="youtube", signal_type="profile_metrics", source_url="https://youtube.com/@example", evidence_span=None, strategy="social_profile_metrics"),
        ]
        result = run_company_control(profile, observations, target=20, minimum_iterations=1)
        self.assertEqual(result["iterations_run"], len(strategy_order([])))
        self.assertEqual(result["final"], development_score(profile, observations))

    def test_exact_wikidata_org_profile_can_supply_external_identity(self):
        profile = {
            "organisation_number": "923609016",
            "name": "Example AS",
            "evidence": {"website": {"value": {"identity_assessment": {"publishable": False}}}},
        }
        wikidata = self.observation(
            platform="wikidata",
            signal_type="company_profile",
            source_url="https://www.wikidata.org/wiki/Q123",
            evidence_span="Q123: P2333=923609016",
            source_class="open_knowledge_graph",
            strategy="company_site_identity",
        )
        score = development_score(profile, [wikidata])
        self.assertEqual(score["components"]["exact_external_identity"], 20.0)
        self.assertTrue(publishable_observation(wikidata))

    def test_controller_replicates_prior_winning_strategy_first(self):
        prior = [
            {"strategy": "youtube_channel_feed", "learning_gain": 8.0},
            {"strategy": "verified_handle_extraction", "learning_gain": 2.0},
        ]
        self.assertEqual(strategy_order(prior)[0], "youtube_channel_feed")
        profile = {"organisation_number": "923609016", "name": "Example AS", "evidence": {"website": {"value": {"identity_assessment": {"publishable": True}}}}}
        result = run_company_control(profile, [], prior_iterations=prior, minimum_iterations=1, maximum_iterations=2)
        self.assertEqual(result["iterations"][0]["strategy"], "youtube_channel_feed")
        self.assertEqual(result["iterations"][0]["controller_action"], "replicate")


if __name__ == "__main__":
    unittest.main()
