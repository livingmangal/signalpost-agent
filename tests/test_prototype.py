from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from norway_company_agent.evidence import evidence
from scripts.build_prototype import build as build_prototype, compact as compact_prototype, qualification_copy


class PrototypeTests(unittest.TestCase):
    def test_qualification_copy_keeps_production_boundary_visible(self):
        header, boundary = qualification_copy({
            "weighted_score": {"verified_points": 100, "maximum_points": 100},
            "qualification": {"poc_qualified": True, "production_qualified": False},
        })
        self.assertIn("100/100", header)
        self.assertIn("not production-qualified", header)
        self.assertIn("remain quarantined", boundary)

    def test_quarantined_social_links_are_counted_but_not_published(self):
        row = {
            "organisation_number": "923609016",
            "name": "Subsidiary AS",
            "legal_form": "AS",
            "employees": None,
            "municipality": "OSLO",
            "industry_code": None,
            "industry_label": None,
            "website": "https://parent.test",
            "bankrupt": False,
            "liquidating": False,
            "evidence": {
                "website": evidence(
                    "website",
                    "available",
                    "company_site",
                    "https://parent.test",
                    value={
                        "identity_assessment": {"publishable": False},
                        "social_links": [],
                        "discovered_social_links": [
                            {"platform": "linkedin", "url": "https://linkedin.com/company/parent"}
                        ],
                    },
                )
            },
        }
        website = compact_prototype(row)["web"]["value"]
        self.assertEqual(website["quarantined_social_count"], 1)
        self.assertEqual(website["social_links"], [])

    def test_build_prototype_does_not_crash_on_template_formatting(self):
        row = {
            "organisation_number": "923609016",
            "name": "Equinor ASA",
            "legal_form": "ASA",
            "employees": 20000,
            "municipality": "STAVANGER",
            "industry_code": "06.100",
            "industry_label": "Oil & Gas",
            "website": "https://www.equinor.com",
            "bankrupt": False,
            "liquidating": False,
            "evidence": {},
        }
        html_out = build_prototype([row], score={"raw_score": 85})
        self.assertIn("<!doctype html>", html_out)
        self.assertIn("Equinor ASA", html_out)
        self.assertIn("923609016", html_out)


    def test_compact_handles_envelope_and_contract_shapes(self):
        envelope_row = {
            "run_id": "test_run",
            "organisation_number": "923609016",
            "profile": {
                "organisation_number": "923609016",
                "name": "Equinor ASA",
                "legal_form": "ASA",
                "employees": 20000,
                "municipality": "STAVANGER",
                "industry_code": "06.100",
                "industry_label": "Oil & Gas",
                "website": "https://www.equinor.com",
                "bankrupt": False,
                "liquidating": False,
                "evidence": {},
            },
        }
        res_env = compact_prototype(envelope_row)
        self.assertEqual(res_env["name"], "Equinor ASA")
        self.assertEqual(res_env["org"], "923609016")

        contract_row = {
            "organisation_number": "923609016",
            "claims": [
                {"field": "company_name", "value": "Equinor ASA"},
                {"field": "employee_count", "value": 20000},
                {"field": "legal_form", "value": "ASA"},
                {"field": "municipality", "value": "STAVANGER"},
            ],
            "evidence": [
                {"id": "ev-1", "source_url": "https://data.brreg.no"}
            ],
        }
        res_contract = compact_prototype(contract_row)
        self.assertEqual(res_contract["name"], "Equinor ASA")
        self.assertEqual(res_contract["employees"], 20000)


if __name__ == "__main__":
    unittest.main()

