"""Legacy test aggregator for backwards-compatibility with existing runners.

Individual modular test suites are located in:
- tests/test_evidence.py
- tests/test_external_footprint.py
- tests/test_completeness.py
- tests/test_sampling.py
- tests/test_operations.py
- tests/test_website.py
- tests/test_discovery.py
- tests/test_sentiment.py
- tests/test_official.py
- tests/test_research.py
- tests/test_prototype.py
- tests/test_refresh.py
- tests/test_models.py
"""
from __future__ import annotations

import unittest

from tests.test_evidence import EvidenceTests
from tests.test_external_footprint import ExternalFootprintTests
from tests.test_completeness import CompletenessScoreTests
from tests.test_sampling import SamplingTests
from tests.test_operations import OperationsTests
from tests.test_website import WebsiteTests, WebsiteIdentityTests, VerifiedSiteSeedTests
from tests.test_discovery import DiscoveryTests
from tests.test_sentiment import SentimentTests
from tests.test_official import OfficialNormalizationTests
from tests.test_research import ResearchAgentTests
from tests.test_prototype import PrototypeTests
from tests.test_refresh import RefreshTests

ALL_TEST_CASES = [
    EvidenceTests,
    ExternalFootprintTests,
    CompletenessScoreTests,
    SamplingTests,
    OperationsTests,
    WebsiteTests,
    WebsiteIdentityTests,
    VerifiedSiteSeedTests,
    DiscoveryTests,
    SentimentTests,
    OfficialNormalizationTests,
    ResearchAgentTests,
    PrototypeTests,
    RefreshTests,
]


def load_tests(loader, standard_tests, pattern):
    """Avoid duplicate test runs during discovery while supporting direct execution."""
    if pattern:
        return unittest.TestSuite()
    suite = unittest.TestSuite()
    for test_class in ALL_TEST_CASES:
        suite.addTests(loader.loadTestsFromTestCase(test_class))
    return suite


if __name__ == "__main__":
    unittest.main()
