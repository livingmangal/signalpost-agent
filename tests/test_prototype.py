from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from norway_company_agent.evidence import evidence
from scripts.build_prototype import compact as compact_prototype, qualification_copy


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


if __name__ == "__main__":
    unittest.main()
