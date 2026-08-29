#!/usr/bin/env python3
"""Descriptive bm25 measurement: ranked search cost and flip reachability.

Generates deterministic synthetic corpora at bounded scales, measures ranked
versus unranked query cost through the real library (gate included), and
counts how often corpus growth changes the ranked order of an unchanged
matched set — with additions that share query terms and with lexically
unrelated additions. Measurements are descriptive evidence per decision
0015; nothing is pinned or asserted beyond sanity bounds.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from artifact_memory.canonical import canonical_bytes, sha256_bytes  # noqa: E402
from artifact_memory.projection import project_records, search_records  # noqa: E402

GENERATOR_PROFILE = "rank-measure/v1:corpus-v2:summaries-v1"
COMMON = ("alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta")
RARE = ("quokka", "wombat", "narwhal", "axolotl", "pangolin", "okapi")
UNRELATED = ("iota", "kappa", "lambda", "mu", "nu", "xi", "omicron", "pi")


def _summary(index: int) -> str:
    words = []
    for position in range(6):
        words.append(COMMON[(index * 7 + position * 3) % len(COMMON)])
    words.append(RARE[index % len(RARE)])
    return " ".join(words)


def _record(index: int) -> dict:
    return {
        "schema_id": "artifact-memory/knowledge-record/v1",
        "record_id": f"record://synthetic/rank-measure-{index:06d}",
        "record_type": "note",
        "lifecycle": "accepted",
        "meaning": {"summary": _summary(index)},
        "artifact_refs": [],
        "provenance": [{"kind": "author", "source_ref": "fixture://synthetic/rank-measure/v1"}],
        "sensitivity": "public",
    }


def _unrelated_record(index: int) -> dict:
    """One lexically unrelated addition, varied per index in length and mix."""
    record = _record(10_000_000 + index)
    words = [UNRELATED[(index * 5 + position * 2) % len(UNRELATED)] for position in range(3 + index % 6)]
    record["meaning"] = {"summary": " ".join(words)}
    return record


def _related_record(index: int) -> dict:
    """One query-term-sharing addition, varied per index in frequency and length."""
    record = _record(20_000_000 + index)
    betas = 1 + index % 4
    gammas = 1 + (index * 3) % 4
    filler = [COMMON[(index + position) % len(COMMON)] for position in range(index % 3)]
    words = ["beta"] * betas + ["gamma"] * gammas + filler + [RARE[index % len(RARE)]]
    record["meaning"] = {"summary": " ".join(words)}
    return record


def _median_ms(action, repeats: int) -> float:
    samples = []
    for _ in range(repeats):
        start = time.perf_counter()
        action()
        samples.append((time.perf_counter() - start) * 1000.0)
    return round(statistics.median(samples), 3)


def _measure_scale(count: int, repeats: int, trials: int) -> dict:
    records = [_record(index) for index in range(count)]
    with tempfile.TemporaryDirectory(prefix=f"rank-measure-{count}-") as temporary:
        workspace = Path(temporary)
        paths = []
        for ordinal, payload in enumerate(records):
            path = workspace / f"record-{ordinal:06d}.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            paths.append(path)
        base_output = workspace / "base"
        start = time.perf_counter()
        base_receipt = project_records(paths, base_output)
        projection_seconds = round(time.perf_counter() - start, 3)
        corpus_digest = sha256_bytes(
            b"".join(canonical_bytes(record) + b"\n" for record in records)
        )
        index = base_output / "records.sqlite"
        query = "beta gamma"
        unranked_ms = _median_ms(lambda: search_records(index, query), repeats)
        ranked_ms = _median_ms(lambda: search_records(index, query, rank=True), repeats)
        base_ranked = search_records(index, query, rank=True)

        flips_unrelated = 0
        flips_related = 0
        for trial in range(trials):
            for maker, bucket in ((_unrelated_record, "unrelated"), (_related_record, "related")):
                grown = workspace / f"grown-{bucket}-{trial}"
                grown.mkdir()
                addition = maker(trial)
                addition_path = grown / "addition.json"
                addition_path.write_text(json.dumps(addition), encoding="utf-8")
                project_records(paths + [addition_path], grown)
                grown_ranked = search_records(grown / "records.sqlite", query, rank=True)
                trimmed = [record_id for record_id in grown_ranked if record_id in set(base_ranked)]
                if trimmed != base_ranked:
                    if bucket == "unrelated":
                        flips_unrelated += 1
                    else:
                        flips_related += 1
        return {
            "record_count": count,
            "corpus_digest": corpus_digest,
            "source_record_set_digest": base_receipt["source_record_set_digest"],
            "projection_build_seconds": projection_seconds,
            "unranked_median_ms": unranked_ms,
            "ranked_median_ms": ranked_ms,
            "ranked_over_unranked_ratio": round(ranked_ms / unranked_ms, 2) if unranked_ms else None,
            "matched_record_count": len(base_ranked),
            "flip_trials": trials,
            "flips_after_unrelated_addition": flips_unrelated,
            "flips_after_related_addition": flips_related,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scales", type=lambda text: [int(part) for part in text.split(",")], default=[1000, 5000])
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--trials", type=int, default=10)
    args = parser.parse_args(argv)
    measurements = [
        _measure_scale(count, args.repeats, args.trials) for count in args.scales
    ]
    receipt = {
        "schema": "artifact-memory/ranked-search-measurement/v1",
        "generator_profile": GENERATOR_PROFILE,
        "sqlite_version": __import__("sqlite3").sqlite_version,
        "python_version": sys.version.split()[0],
        "measurements": measurements,
    }
    json.dump(receipt, sys.stdout, indent=2, sort_keys=True)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
