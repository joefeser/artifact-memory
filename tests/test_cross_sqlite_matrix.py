import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "run_cross_sqlite_matrix.py"
SPEC = importlib.util.spec_from_file_location("run_cross_sqlite_matrix", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
run_cross_sqlite_matrix = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(run_cross_sqlite_matrix)


def _entry(version: str, *, capable: bool) -> dict:
    tier_b = {
        "available": True,
        "clean_read_succeeded": capable,
        "tampered_outcome": "projection-unavailable",
    }
    if capable:
        tier_b.update(
            {
                "source_record_set_digest": "sha-256:synthetic-source",
                "logical_snapshot_digest": "sha-256:synthetic-snapshot",
                "clean_default_order": ["record://synthetic/one"],
                "clean_literal_order": ["record://synthetic/one"],
                "clean_ranked_order": ["record://synthetic/one"],
            }
        )
    else:
        tier_b["clean_read_code"] = "projection-unavailable"
    return {
        "runtime": f"synthetic-{version}",
        "sqlite_version": version,
        "tier_a": {"integrity_check_detects_forgery": capable},
        "tier_b": tier_b,
    }


class CrossSQLiteMatrixTests(unittest.TestCase):
    def test_capable_backport_is_classified_by_behavior(self):
        entries = [
            _entry("3.43.0-backport", capable=True),
            _entry("3.52.0", capable=True),
        ]
        failures, summary = run_cross_sqlite_matrix._assert_invariants(entries)
        self.assertEqual(failures, [])
        self.assertEqual(
            summary["gate_passing_versions"], ["3.43.0-backport", "3.52.0"]
        )

    def test_incapable_newer_build_fails_closed_by_behavior(self):
        entries = [
            _entry("3.46.1", capable=True),
            _entry("3.52.0", capable=True),
            _entry("3.99.0-custom", capable=False),
        ]
        failures, summary = run_cross_sqlite_matrix._assert_invariants(entries)
        self.assertEqual(failures, [])
        self.assertEqual(summary["fail_closed_versions"], ["3.99.0-custom"])


if __name__ == "__main__":
    unittest.main()
