from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from norway_company_agent.evidence import evidence
from norway_company_agent.crawl_events import extract_page_event, merge_profile_events, missing_seed_error_events
from norway_company_agent.identity import apply_website_identity_gate, assess_social_identity, assess_website_identity
from norway_company_agent.website import (
    _extraction_state,
    _priority_links,
    _social_links,
    assert_public_url,
    normalize_homepage,
    normalize_social_url,
    structured_social_links,
)
from scripts.run_scrapy_websites import terminal_events_for_run


class WebsiteTests(unittest.TestCase):
    def test_interrupted_run_does_not_synthesize_terminal_failures(self):
        profiles = [{"organisation_number": "1", "website": "pending.no"}]
        self.assertEqual(terminal_events_for_run(profiles, [], False), [])
        self.assertEqual(len(terminal_events_for_run(profiles, [], True)), 1)

    def test_missing_seed_gets_explicit_terminal_event(self):
        profiles = [
            {"organisation_number": "1", "website": "example.no"},
            {"organisation_number": "2", "website": "blocked.no"},
            {"organisation_number": "3", "website": ""},
        ]
        existing = [{"organisation_number": "1", "status": "available"}]
        missing = missing_seed_error_events(profiles, existing)
        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0]["organisation_number"], "2")
        self.assertEqual(missing[0]["status"], "source_error")
        self.assertIn("robots.txt", missing[0]["error"])

    def test_crawl_event_extraction_and_merge_preserve_page_hashes(self):
        homepage = extract_page_event(
            organisation_number="923609016",
            requested_url="https://example.no/",
            final_url="https://example.no/",
            status_code=200,
            content_type="text/html; charset=utf-8",
            body=b'<html><head><title>Example AS</title><meta name="description" content="Company"></head><body><p>Example AS provides enough substantive company information for extraction and identity review.</p><a href="https://linkedin.com/company/example">LinkedIn</a></body></html>',
            page_kind="homepage",
            retrieved_at="2026-08-22T00:00:00Z",
        )
        secondary = extract_page_event(
            organisation_number="923609016",
            requested_url="https://example.no/contact",
            final_url="https://example.no/contact",
            status_code=200,
            content_type="text/html",
            body=b"<html><title>Contact</title><body>Contact Example AS in Oslo.</body></html>",
            page_kind="priority",
            retrieved_at="2026-08-22T00:00:01Z",
        )
        record = merge_profile_events({"website": "https://example.no"}, [homepage, secondary])
        self.assertEqual(record["status"], "available")
        self.assertEqual(len(record["value"]["pages"]), 2)
        self.assertEqual(record["content_sha256"], homepage["content_sha256"])
        self.assertEqual(record["value"]["scheduler"], "scrapy_resumable_v1")

    def test_footer_identity_is_preserved_for_exact_company_gate(self):
        event = extract_page_event(
            organisation_number="985628572",
            requested_url="https://netsolution.no/",
            final_url="https://netsolution.no/",
            status_code=200,
            content_type="text/html",
            body=(
                b'<html><head><title>IT services</title></head><body><main>Useful services for customers.</main>'
                b'<footer>Netsolution Viken AS, Kobbervikdalen 75 A, 3036 Drammen</footer></body></html>'
            ),
            page_kind="homepage",
            retrieved_at="2026-08-23T00:00:00Z",
        )
        website = merge_profile_events({"website": "https://netsolution.no/"}, [event])
        profile = {
            "organisation_number": "985628572",
            "name": "NETSOLUTION VIKEN AS",
            "evidence": {"website": website},
        }
        self.assertIn("Netsolution Viken AS", website["value"]["identity_text_excerpt"])
        self.assertTrue(assess_website_identity(profile)["publishable"])

    def test_normalizes_registry_hostname(self):
        self.assertEqual(normalize_homepage("example.no"), "https://example.no/")
        self.assertEqual(normalize_homepage("http://example.no"), "http://example.no/")

    def test_only_extracts_declared_social_links(self):
        soup = BeautifulSoup('<a href="https://www.linkedin.com/company/example/">LinkedIn</a><a href="/about">About</a>', "html.parser")
        self.assertEqual(_social_links("https://example.no", soup), [{"platform": "linkedin", "url": "https://linkedin.com/company/example"}])

    def test_extracts_embedded_company_social_profiles(self):
        soup = BeautifulSoup(
            '<div class="fb-page" data-href="https://www.facebook.com/ExampleCompany"></div>'
            '<iframe src="https://www.facebook.com/plugins/page.php?href=https%3A%2F%2Fwww.facebook.com%2FSecondCompany"></iframe>',
            "html.parser",
        )
        self.assertEqual(
            _social_links("https://example.no/", soup),
            [
                {"platform": "facebook", "url": "https://facebook.com/ExampleCompany"},
                {"platform": "facebook", "url": "https://facebook.com/SecondCompany"},
            ],
        )

    def test_extracts_schema_same_as_company_social_profiles(self):
        value = [{
            "@type": "Organization",
            "sameAs": [
                "https://www.facebook.com/ExampleCompany/",
                "https://instagram.com/examplecompany",
                "https://linkedin.com/in/example-person",
            ],
        }]
        self.assertEqual(
            structured_social_links(value),
            [
                {"platform": "facebook", "url": "https://facebook.com/ExampleCompany"},
                {"platform": "instagram", "url": "https://instagram.com/examplecompany"},
            ],
        )

    def test_social_profiles_reject_share_event_group_and_policy_links(self):
        rejected = (
            "https://facebook.com/sharer.php?u=x", "https://facebook.com/events/123",
            "https://facebook.com/groups/123", "https://facebook.com/policy.php",
            "https://facebook.com/privacy/explanation",
            "https://linkedin.com/shareArticle?url=x", "https://instagram.com/p/abc",
        )
        self.assertTrue(all(normalize_social_url(url) is None for url in rejected))

    def test_social_profiles_canonicalize_www_variants(self):
        self.assertEqual(normalize_social_url("https://www.facebook.com/Example/"), {"platform": "facebook", "url": "https://facebook.com/Example"})
        self.assertEqual(normalize_social_url("https://linkedin.com/company/example/admin/feed/posts"), {"platform": "linkedin", "url": "https://linkedin.com/company/example"})
        self.assertEqual(normalize_social_url("https://youtube.com/channel/abc/featured"), {"platform": "youtube", "url": "https://youtube.com/channel/abc"})
        self.assertIsNone(normalize_social_url("https://facebook.com/profile.php"))
        self.assertIsNone(normalize_social_url("https://[object Object]"))

    def test_priority_pages_stay_on_exact_site(self):
        soup = BeautifulSoup('<a href="/kontakt">Contact</a><a href="https://other.no/about">About</a><a href="/products">Products</a>', "html.parser")
        self.assertEqual(_priority_links("https://example.no/", soup), ["https://example.no/kontakt"])

    def test_js_shell_is_only_a_fallback_candidate(self):
        shell = BeautifulSoup('<html><script src="a.js"></script><script src="b.js"></script></html>', "html.parser")
        self.assertEqual(_extraction_state("", shell), "js_fallback_candidate")
        self.assertEqual(_extraction_state("A" * 100, shell), "static_complete")

    def test_blocks_local_network_targets(self):
        for url in ("http://127.0.0.1/admin", "http://localhost/", "http://169.254.169.254/latest/meta-data"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                assert_public_url(url)


class WebsiteIdentityTests(unittest.TestCase):
    def test_group_contact_page_listing_subsidiary_org_number_is_not_exact_homepage_identity(self):
        profile = {
            "organisation_number": "915637353",
            "name": "SKS PRODUKSJON AS",
            "evidence": {"website": evidence("website", "available", "company_site", "https://sks.no", value={
                "final_url": "https://sks.no/",
                "title": "Konsern - SKS - Forside",
                "main_text_excerpt": "SKS is a power group with multiple subsidiaries.",
                "pages": [{"title": "Contact", "main_text_excerpt": "SKS Produksjon AS organisation number 915 637 353"}],
            })},
        }
        assessment = assess_website_identity(profile)
        self.assertFalse(assessment["publishable"])
        self.assertNotEqual(assessment["score"], 1.0)

    def test_shared_identity_gate_quarantines_parent_social_links(self):
        website = evidence("website", "available", "company_site", "https://parent.test", value={
            "title": "Parent Group", "main_text_excerpt": "Parent Group portfolio",
            "social_links": [{"platform": "linkedin", "url": "https://linkedin.com/company/parent"}],
        })
        profile = {"organisation_number": "923609016", "name": "Exact Subsidiary AS", "evidence": {}}
        result = apply_website_identity_gate(profile, website)
        self.assertFalse(result["assessment"]["publishable"])
        self.assertEqual(result["website"]["value"]["social_links"], [])
        self.assertEqual(result["quarantined_social_links"], 1)

    def test_exact_legal_name_is_publishable(self):
        row = {"organisation_number": "923609016", "name": "Norsk Fiskeeksport AS", "evidence": {"website": {"status": "available", "value": {"title": "Norsk Fiskeeksport AS"}}}}
        self.assertTrue(assess_website_identity(row)["publishable"])

    def test_parent_brand_without_legal_name_is_quarantined(self):
        row = {"organisation_number": "988412406", "name": "Tevlingveien 23 Invest AS", "evidence": {"website": {"status": "available", "value": {"title": "Ragde Eiendom"}}}}
        self.assertFalse(assess_website_identity(row)["publishable"])

    def test_parked_domain_and_parent_company_sports_site_are_quarantined(self):
        parked = {"organisation_number": "996081001", "name": "Condalign AS", "evidence": {"website": {"status": "available", "value": {"title": "CondAlign.com is for sale | HugeDomains"}}}}
        sports = {"organisation_number": "996242692", "name": "Primulator B.I.L.", "evidence": {"website": {"status": "available", "value": {"title": "Primulator", "description": "Premium products for HoReCa"}}}}
        self.assertFalse(assess_website_identity(parked)["publishable"])
        self.assertFalse(assess_website_identity(sports)["publishable"])

    def test_hosting_placeholder_and_generic_link_page_are_quarantined(self):
        hosting = {"organisation_number": "917568278", "name": "HJELMEN AS", "evidence": {"website": {"status": "available", "value": {"title": "www.Hjelmen-as.no is parked at Miss Hosting Web Hosting", "main_text_excerpt": "Hjelmen " * 100}}}}
        links = {"organisation_number": "986606009", "name": "KOALA ANS", "evidence": {"website": {"status": "available", "value": {"title": "koala.no", "description": "Find the best information and most relevant links on all topics related to"}}}}
        self.assertFalse(assess_website_identity(hosting)["publishable"])
        self.assertFalse(assess_website_identity(links)["publishable"])

    def test_broader_umbrella_site_is_not_exact_when_name_only_appears_in_body(self):
        row = {
            "organisation_number": "976994027",
            "name": "AVALDSNES SOKN",
            "evidence": {"website": {"status": "available", "value": {
                "title": "Kirken i Karmøy",
                "final_url": "https://www.karmoykirken.no/",
                "main_text_excerpt": "Avaldsnes sokn is one of several parishes represented on this umbrella site.",
            }}},
        }
        self.assertFalse(assess_website_identity(row)["publishable"])

    def test_social_handle_requires_exact_entity_name_evidence(self):
        aon = {"name": "Aon Norway AS"}
        fish = {"name": "Norsk Fiskeeksport AS"}
        self.assertFalse(assess_social_identity(aon, {"platform": "linkedin", "url": "https://linkedin.com/company/aon"})["publishable"])
        self.assertTrue(assess_social_identity(fish, {"platform": "linkedin", "url": "https://linkedin.com/company/norsk-fiskeeksport"})["publishable"])


class VerifiedSiteSeedTests(unittest.TestCase):
    def test_verified_seed_is_applied_and_unknown_org_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profiles = root / "profiles.jsonl"
            seeds = root / "seeds.json"
            output = root / "output.jsonl"
            report = root / "report.json"
            profiles.write_text(json.dumps({"organisation_number": "123456789", "name": "Example AS"}) + "\n")
            seeds.write_text(json.dumps([{
                "organisation_number": "123456789",
                "website": "https://example.no/",
                "proof_url": "https://source.example/proof",
                "proof": "Exact name and organisation number",
            }]))
            command = [
                sys.executable, str(ROOT / "scripts" / "apply_verified_site_seeds.py"),
                "--profiles", str(profiles), "--seeds", str(seeds),
                "--output", str(output), "--report", str(report),
            ]
            subprocess.run(command, check=True, capture_output=True, text=True)
            row = json.loads(output.read_text().strip())
            self.assertEqual(row["website"], "https://example.no/")
            self.assertEqual(row["website_seed_source"], "independently_verified_exact_entity")
            self.assertEqual(json.loads(report.read_text())["applied"], 1)

            seeds.write_text(json.dumps([{
                "organisation_number": "987654321",
                "website": "https://unknown.no/",
                "proof_url": "https://source.example/proof",
            }]))
            failed = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("unknown organisations", failed.stderr)


if __name__ == "__main__":
    unittest.main()
