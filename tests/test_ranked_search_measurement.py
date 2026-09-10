import argparse
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "measure_ranked_search.py"
SPEC = importlib.util.spec_from_file_location("measure_ranked_search", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
measure_ranked_search = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(measure_ranked_search)


class RankedSearchMeasurementTests(unittest.TestCase):
    def test_scales_require_at_least_two_records(self):
        for value in ("0", "1", "1000,1"):
            with self.subTest(value=value):
                with self.assertRaises(argparse.ArgumentTypeError):
                    measure_ranked_search._parse_scales(value)

    def test_scales_preserve_requested_counts(self):
        self.assertEqual(measure_ranked_search._parse_scales("2,1000"), [2, 1000])


if __name__ == "__main__":
    unittest.main()
