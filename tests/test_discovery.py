from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from norway_company_agent.discovery import (
    build_company_search_query,
    choose_search_candidate,
    parse_brave_web_results,
    score_search_candidate,
)
from scripts.run_brave_discovery import brave_search


class DiscoveryTests(unittest.TestCase):
    def test_brave_request_keeps_key_out_of_url_and_parses_in_memory(self):
        captured = {}

        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps({"web": {"results": [{
                    "url": "https://example.no", "title": "Example AS", "description": "Example in Oslo",
                }]}}).encode()

        def fake_open(request, timeout):
            captured["url"] = request.full_url
            captured["key"] = request.get_header("X-subscription-token")
            captured["timeout"] = timeout
            return Response()

        with patch("scripts.run_brave_discovery.urllib.request.urlopen", fake_open):
            results, operation = brave_search({
                "name": "Example AS", "organisation_number": "999999999", "municipality": "OSLO",
            }, "secret-test-key", timeout=3.0, count=5)
        self.assertEqual(len(results), 1)
        self.assertEqual(operation["status"], 200)
        self.assertNotIn("secret-test-key", captured["url"])
        self.assertEqual(captured["key"], "secret-test-key")
        self.assertEqual(captured["timeout"], 3.0)

    def test_company_query_contains_exact_name_org_and_location(self):
        query = build_company_search_query({
            "name": "Norsk Fiskeeksport AS", "organisation_number": "923 609 016", "municipality": "NOTODDEN",
        })
        self.assertEqual(query, '"Norsk Fiskeeksport AS" 923609016 NOTODDEN')

    def test_brave_parser_is_provider_neutral_candidate_input(self):
        results = parse_brave_web_results({"web": {"results": [
            {"url": "https://example.no", "title": "Example AS", "description": "Example in Oslo"},
            {"title": "Missing URL"},
        ]}}, query='"Example AS" 999999999')
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["provider"], "brave_search_api")
        self.assertEqual(results[0]["rank"], 1)

    def test_directory_and_social_results_are_not_company_site_candidates(self):
        profile = {"organisation_number": "923609016", "name": "Example Norge AS", "municipality": "OSLO"}
        for url in ("https://proff.no/selskap/example", "https://linkedin.com/company/example"):
            with self.subTest(url=url):
                self.assertEqual(score_search_candidate(profile, {"url": url, "title": "Example Norge AS"})["status"], "rejected")

    def test_exact_name_in_title_and_host_is_only_a_crawl_candidate(self):
        profile = {"organisation_number": "923609016", "name": "Norsk Fiskeeksport AS", "municipality": "NOTODDEN"}
        decision = choose_search_candidate(profile, [{
            "url": "https://norskfiskeeksport.no/",
            "title": "Norsk Fiskeeksport AS",
            "snippet": "Seafood exporter in Notodden",
            "rank": 1,
            "provider": "fixture",
        }])
        self.assertFalse(decision["abstained"])
        self.assertEqual(decision["selected"]["status"], "accepted_for_crawl")
        self.assertIn("Publication still requires", decision["policy"])

    def test_ambiguous_name_match_without_host_support_abstains(self):
        profile = {"organisation_number": "923609016", "name": "Norsk Fiskeeksport AS", "municipality": "NOTODDEN"}
        decision = choose_search_candidate(profile, [{"url": "https://parent-group.no/", "title": "Norsk Fiskeeksport AS - portfolio", "snippet": "Group companies"}])
        self.assertTrue(decision["abstained"])


if __name__ == "__main__":
    unittest.main()
