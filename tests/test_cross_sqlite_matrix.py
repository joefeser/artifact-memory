import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


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
    def test_distinct_local_runtimes_with_same_version_are_retained(self):
        paths = {
            "python3": "/synthetic/python-a",
            "python3.11": "/synthetic/python-b",
        }
        report = {
            "python_version": "3.14.0",
            "sqlite_version": "3.52.0",
            "tier_a": {"integrity_check_detects_forgery": True},
            "tier_b": {"available": False, "reason": "synthetic"},
        }
        completed = mock.Mock(stdout=json.dumps(report))
        with mock.patch.object(
            run_cross_sqlite_matrix.shutil,
            "which",
            side_effect=lambda name: paths.get(name),
        ), mock.patch.object(
            run_cross_sqlite_matrix.subprocess,
            "run",
            return_value=completed,
        ):
            entries = run_cross_sqlite_matrix._run_local()
        self.assertEqual([entry["runtime"] for entry in entries], [
            "python3 (/synthetic/python-a)",
            "python3.11 (/synthetic/python-b)",
        ])

    def test_distinct_cli_paths_with_same_version_are_bounded_and_retained(self):
        with tempfile.TemporaryDirectory() as temporary:
            first = Path(temporary) / "sqlite-a"
            second = Path(temporary) / "sqlite-b"
            first.touch()
            second.touch()
            completed = [
                mock.Mock(stdout="3.52.0 2026-01-01\n"),
                mock.Mock(stdout="ok\n"),
                mock.Mock(stdout="3.52.0 2026-01-01\n"),
                mock.Mock(stdout="ok\n"),
            ]
            with mock.patch.object(
                run_cross_sqlite_matrix,
                "CLI_BINARIES",
                (str(first), str(second)),
            ), mock.patch.object(
                run_cross_sqlite_matrix.subprocess,
                "run",
                side_effect=completed,
            ) as run:
                entries = run_cross_sqlite_matrix._run_cli_binaries()
        self.assertEqual(len(entries), 2)
        self.assertEqual([entry["sqlite_version"] for entry in entries], ["3.52.0", "3.52.0"])
        self.assertEqual([call.kwargs["timeout"] for call in run.call_args_list], [30, 180, 30, 180])

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

    def test_incapable_runtime_must_use_projection_unavailable(self):
        entries = [
            _entry("3.46.1", capable=True),
            _entry("3.52.0", capable=True),
            _entry("3.99.0-custom", capable=False),
        ]
        entries[-1]["tier_b"]["clean_read_code"] = "query-invalid"
        failures, summary = run_cross_sqlite_matrix._assert_invariants(entries)
        self.assertIn(
            "synthetic-3.99.0-custom: incapable runtime failed with 'query-invalid' instead of projection-unavailable",
            failures,
        )
        self.assertEqual(summary["fail_closed_versions"], [])


if __name__ == "__main__":
    unittest.main()
