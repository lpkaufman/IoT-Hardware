import unittest

from onshape_jira.config import (
    DEFAULT_INVESTMENTS_CATEGORY,
    _http_timeout_seconds,
    _normalize_investment_category_value,
)


class ConfigInvestmentCategoryNormalizationTest(unittest.TestCase):
    def test_ascii_hyphen_coerces_to_canonical_default(self):
        normalized = _normalize_investment_category_value(
            "Planned - Product & Engineering"
        )
        self.assertEqual(normalized, DEFAULT_INVESTMENTS_CATEGORY)

    def test_http_timeout_seconds_default_and_bounds(self):
        self.assertAlmostEqual(_http_timeout_seconds({}), 60.0)
        self.assertAlmostEqual(
            _http_timeout_seconds({"HTTP_TIMEOUT_SECONDS": "90.5"}), 90.5
        )
        with self.assertRaises(ValueError):
            _http_timeout_seconds({"HTTP_TIMEOUT_SECONDS": "-1"})
        with self.assertRaises(ValueError):
            _http_timeout_seconds({"HTTP_TIMEOUT_SECONDS": "601"})


if __name__ == "__main__":
    unittest.main()
