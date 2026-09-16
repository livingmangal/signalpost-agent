from __future__ import annotations

import collections
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from norway_company_agent.evidence import evidence
from norway_company_agent.official import _reserve_history_slot
from norway_company_agent.operations import domain_request_summary, latency_summary, percentile
from norway_company_agent.batch import (
    evidence_terminal_state,
    profile_complete_for_modules,
    read_organisation_inputs,
    terminal_envelope,
    validate_envelopes,
)


class OperationsTests(unittest.TestCase):
    def test_history_rate_limiter_spaces_request_starts_not_responses(self):
        import norway_company_agent.official as official

        old = official._history_last_request
        now = [10.0]
        sleeps = []

        def clock():
            return now[0]

        def sleeper(delay):
            sleeps.append(delay)
            now[0] += delay

        try:
            official._history_last_request = 9.0
            _reserve_history_slot(clock, sleeper)
            self.assertAlmostEqual(sleeps[0], 1.1)
            self.assertAlmostEqual(official._history_last_request, 11.1)
            now[0] = 13.3
            _reserve_history_slot(clock, sleeper)
            self.assertEqual(len(sleeps), 1)
            self.assertAlmostEqual(official._history_last_request, 13.3)
        finally:
            official._history_last_request = old

    def test_batch_input_preserves_split_annotations(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "orgs.jsonl"
            path.write_text(json.dumps({"organisation_number": "923609016", "evaluation_split": "held_out", "sample_slice": "stress", "ignored": "x"}) + "\n", encoding="utf-8")
            self.assertEqual(read_organisation_inputs(path), [{"organisation_number": "923609016", "evaluation_split": "held_out", "sample_slice": "stress"}])

    def test_batch_contract_emits_exact_terminal_envelopes(self):
        profile = {
            "organisation_number": "923609016",
            "evidence": {
                "registry": evidence("registry", "available", "official", "https://example.test", content_sha256="a" * 64),
                "website": evidence("website", "blocked", "company_site", "https://example.test", note="robots.txt denied"),
            },
        }
        envelope = terminal_envelope(profile, run_id="day-1", modules=["registry", "website"], started_at="2026-01-01T00:00:00Z", completed_at="2026-01-01T00:01:00Z")
        self.assertEqual(envelope["modules"]["registry"]["state"], "complete")
        self.assertEqual(envelope["modules"]["website"]["state"], "blocked_robots")
        self.assertTrue(validate_envelopes([envelope], 1)["passed"])
        self.assertFalse(validate_envelopes([envelope], 2)["passed"])

    def test_unknown_evidence_state_is_submission_error(self):
        self.assertEqual(evidence_terminal_state({"status": "not_fetched"}), "submission_error")

    def test_batch_resume_only_skips_profiles_with_all_terminal_modules(self):
        complete = {"evidence": {"registry": {"status": "available"}, "website": {"status": "not_found"}}}
        partial = {"evidence": {"registry": {"status": "available"}, "website": {"status": "not_fetched"}}}
        self.assertTrue(profile_complete_for_modules(complete, ["registry", "website"]))
        self.assertFalse(profile_complete_for_modules(partial, ["registry", "website"]))

    def test_nearest_rank_percentiles_are_deterministic(self):
        self.assertEqual(percentile([1, 2, 3, 4, 100], 0.5), 3)
        self.assertEqual(percentile([1, 2, 3, 4, 100], 0.95), 100)
        self.assertEqual(latency_summary([1, 2, 3]), {"n": 3, "p50_ms": 2.0, "p95_ms": 3.0, "max_ms": 3.0})

    def test_domain_fairness_summary_preserves_tail(self):
        result = domain_request_summary(collections.Counter({"a.no": 1, "b.no": 2, "c.no": 9}))
        self.assertEqual(result["domains"], 3)
        self.assertEqual(result["p50_requests"], 2.0)
        self.assertEqual(result["max_requests"], 9)


if __name__ == "__main__":
    unittest.main()
