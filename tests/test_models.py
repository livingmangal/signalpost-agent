from __future__ import annotations

import sys
import unittest
from pathlib import Path
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from norway_company_agent.models import (
    AvailabilityState,
    TerminalBatchState,
    EvidenceModel,
    ClaimModel,
    RunMetadataModel,
    OperationsMetricModel,
    ChangeRecordModel,
    OutputContractEnvelope,
    BatchTerminalEnvelope,
    validate_batch_envelope,
    validate_output_contract_envelope,
)


class ModelContractTests(unittest.TestCase):
    def test_availability_state_values(self):
        self.assertEqual(AvailabilityState.AVAILABLE.value, "available")
        self.assertEqual(AvailabilityState.NOT_AVAILABLE.value, "not_available")
        self.assertEqual(AvailabilityState.BLOCKED.value, "blocked")
        self.assertEqual(AvailabilityState.NOT_APPLICABLE.value, "not_applicable")
        self.assertEqual(AvailabilityState.AMBIGUOUS.value, "ambiguous")
        self.assertEqual(AvailabilityState.FAILED.value, "failed")

    def test_terminal_batch_state_values(self):
        self.assertEqual(TerminalBatchState.COMPLETE.value, "complete")
        self.assertEqual(TerminalBatchState.NOT_FOUND.value, "not_found")
        self.assertEqual(TerminalBatchState.BLOCKED_POLICY.value, "blocked_policy")
        self.assertEqual(TerminalBatchState.BUDGET_EXHAUSTED.value, "budget_exhausted")

    def test_evidence_model_validation(self):
        valid_evidence = {
            "id": "ev-001",
            "source_class": "official_annual_accounts",
            "source_url": "https://example.test/accounts",
            "retrieved_at": "2026-08-20T12:00:00Z",
            "value": {"revenue": 1000000},
            "content_sha256": "a" * 64,
            "status": "available",
        }
        item = EvidenceModel.model_validate(valid_evidence)
        self.assertEqual(item.id, "ev-001")
        self.assertEqual(item.status, "available")
        self.assertEqual(item.value, {"revenue": 1000000})

    def test_evidence_model_allows_zero_as_value(self):
        ev = EvidenceModel.model_validate({
            "source_class": "official_registry_bulk",
            "source_url": "https://example.test",
            "retrieved_at": "2026-08-20T12:00:00Z",
            "value": 0,
        })
        self.assertEqual(ev.value, 0)

    def test_claim_model_confidence_range(self):
        claim_data = {
            "field": "has_website",
            "value": "https://example.no",
            "availability": AvailabilityState.AVAILABLE,
            "confidence": 0.95,
            "evidence_ids": ["ev-1"],
        }
        claim = ClaimModel.model_validate(claim_data)
        self.assertEqual(claim.confidence, 0.95)
        self.assertEqual(claim.availability, AvailabilityState.AVAILABLE)

        # Confidence > 1.0 or < 0.0 should fail
        with self.assertRaises(ValidationError):
            ClaimModel.model_validate({**claim_data, "confidence": 1.5})
        with self.assertRaises(ValidationError):
            ClaimModel.model_validate({**claim_data, "confidence": -0.1})

    def test_output_contract_envelope(self):
        payload = {
            "organisation_number": "923609016",
            "run": {
                "run_id": "run-001",
                "started_at": "2026-08-20T12:00:00Z",
                "completed_at": "2026-08-20T12:05:00Z",
                "terminal_status": "completed",
            },
            "claims": [
                {
                    "field": "name",
                    "value": "ACME AS",
                    "availability": "available",
                    "confidence": 1.0,
                }
            ],
            "evidence": [
                {
                    "source_class": "official",
                    "source_url": "https://data.brreg.no/enhetsregisteret/api/enheter/923609016",
                    "retrieved_at": "2026-08-20T12:00:00Z",
                    "value": "ACME AS",
                }
            ],
            "changes": [],
            "operations": {
                "requests": 5,
                "bytes": 12000,
                "p50_ms": 120.5,
            },
        }
        envelope = validate_output_contract_envelope(payload)
        self.assertEqual(envelope.organisation_number, "923609016")
        self.assertEqual(envelope.run.run_id, "run-001")
        self.assertEqual(len(envelope.claims), 1)
        self.assertEqual(envelope.operations.requests, 5)

        # Invalid organisation number (< 9 digits or non-numeric) fails
        bad_org = payload.copy()
        bad_org["organisation_number"] = "123"
        with self.assertRaises(ValidationError):
            validate_output_contract_envelope(bad_org)

    def test_validate_batch_envelope_helper(self):
        batch_record = {
            "run_id": "run-001",
            "organisation_number": "923609016",
            "state": "complete",
            "started_at": "2026-08-20T12:00:00Z",
            "completed_at": "2026-08-20T12:05:00Z",
            "modules": {
                "official": {
                    "state": "complete",
                    "retry_count": 0,
                    "final_timestamp": "2026-08-20T12:02:00Z",
                }
            },
            "profile": {
                "organisation_number": "923609016",
                "name": "ACME AS",
            },
        }
        validated = validate_batch_envelope(batch_record)
        self.assertEqual(validated.organisation_number, "923609016")
        self.assertEqual(validated.state, "complete")
        self.assertIn("official", validated.modules)


if __name__ == "__main__":
    unittest.main()
