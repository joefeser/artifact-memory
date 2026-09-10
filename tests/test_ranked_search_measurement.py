import argparse
import importlib.util
import io
import unittest
from contextlib import redirect_stderr
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

    def test_repeat_and_trial_counts_must_be_positive(self):
        for value in ("0", "-1", "not-an-integer"):
            with self.subTest(value=value):
                with self.assertRaises(argparse.ArgumentTypeError):
                    measure_ranked_search._positive_int(value)

    def test_positive_repeat_and_trial_counts_are_preserved(self):
        self.assertEqual(measure_ranked_search._positive_int("3"), 3)

    def test_cli_rejects_nonpositive_repeat_and_trial_counts_before_measurement(self):
        for args in (
            ["--scales", "2", "--repeats", "0"],
            ["--scales", "2", "--trials", "-1"],
        ):
            with self.subTest(args=args), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    measure_ranked_search.main(args)
            self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
