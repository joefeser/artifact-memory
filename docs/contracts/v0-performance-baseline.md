# v0 performance and resource-safety baseline

The checked benchmark is a descriptive observation, not a capacity promise.
Its synthetic profile contains 1,024 files, an 8 MiB multi-chunk file, 32
directory levels (33 path components including the filename), repeated and
unique bytes, and 1,024 canonical records. The
profile and deterministic corpus identities are replayed on every conformance
run; wall times and traced allocations remain machine-specific measurements.

Run the checked profile with:

```sh
python3 scripts/run_benchmark.py --check
```

The Python API keeps the pre-existing v1 callable as
`run_baseline(file_count, file_size, depth)`. Profile-driven callers use the
explicit `run_baseline_v2(profile)` entry point. Receipt validation dispatches
on `schema_id`; a v2 caller that needs profile provenance binding supplies the
expected profile or digest. Without that external input, validation proves
only structural and internal integrity, not who selected the profile.

The `fixtures/synthetic/benchmarks/v1/` directory is versioned for the
`artifact-memory/benchmark-profile/v1` contract. It contains a
`artifact-memory/benchmark-receipt/v2` expected receipt; consumers select that
receipt schema from its `schema_id`, not from the directory suffix.

Projection records used for timing are explicitly generated, ephemeral
benchmark inputs—not durable canonical knowledge. The profile declares the
versioned `artifact-memory/synthetic-benchmark-record-generator/v1`; the v2
receipt binds that generator and the digest of the exact generated record set.
Changing record-generation semantics requires a new generator identifier and
updated checked evidence. The temporary records and SQLite projection remain
replaceable after the receipt is produced.

The v2 receipt separates reproducible facts from observations:

- `profile_digest`, tree identity, record-set identity, corpus dimensions,
  bounded outcomes, policies, structured claims, and limitations must replay
  exactly;
- every structured claim binds its evidence fields and synthetic profile
  provenance while remaining explicitly `integrity-verified /
  issuer-unverified`;
- scan, projection, and SQLite-only rebuild times are integer microseconds;
- hashing throughput is observed admitted bytes divided by scan wall time;
- peak memory is measured with Python `tracemalloc` and therefore excludes
  operating-system cache and native-library allocation;
- the checked receipt records the runner family without publishing a hostname,
  path, account, or machine identifier.

## Bounded outcomes

The same run proves that byte and entry limits return `partial` with
`resource-limit`, caller cancellation returns `cancelled`, and an unavailable
root returns `failed`. A deterministic synthetic observer event proves that a
file changing during admission remains `partial` with `unstable`; it does not
claim a host-filesystem race was reproduced. A deeply nested synthetic ZIP is
inspected only at the outer level: inner archive bytes remain opaque and no
recursive expansion occurs.

The scanner hashes every admitted regular-file byte. There is no arbitrary
large-file exemption, including no two-gigabyte threshold. Caller-owned scan
bounds still apply before hashing a file that exceeds the remaining byte
budget. Archive entry and uncompressed-byte limits are separately explicit.

## Harness safety

The benchmark validates its profile before creating data. The harness caps a
single corpus at 512 MiB, 100,000 aggregate corpus-plus-record input files, 64
requested directory levels, and 100,000 projection records. These are
benchmark-execution safety ceilings, not
Artifact Memory protocol limits or universal supported maxima. Raising them
requires a reviewed profile and must not weaken scan, archive, cancellation,
or incomplete-result semantics.

The profile schema publishes each direct numeric ceiling. Arithmetic and
generated-payload relationships between profile fields are enforced by
`validate_profile()` because standard JSON Schema cannot compare sibling
numeric values; schema-only acceptance is therefore not execution admission.

## Ranked-search measurements (2026-08-28)

`scripts/measure_ranked_search.py` (descriptive, per decision 0015; generator
profile `rank-measure/v1:corpus-v2:summaries-v1`, corpus digest bound per
scale) measured bm25-ranked versus unranked search through the real library —
integrity gate, contract validation, and match included — on deterministic
synthetic corpora (Python 3.14.4, SQLite 3.52.0):

| Records | Corpus digest (prefix) | Projection build | Unranked median | Ranked median | Ratio |
| --- | --- | --- | --- | --- | --- |
| 1,000 | sha-256:01c29a4b… | 0.135 s | 56.0 ms | 56.2 ms | 1.00 |
| 5,000 | sha-256:d3d0d5a0… | 0.674 s | 288.4 ms | 287.9 ms | 1.00 |

Ranked search is at cost parity with unranked search: per-query cost is
dominated by per-query revalidation (consistent with the audit's ~315 ms per
5,000-record measurement), and bm25 ordering added no measurable overhead at
either scale.

Flip reachability at scale: across forty distinct single-record additions —
at each scale, ten lexically unrelated additions and ten query-term-sharing
additions, each varied in length and term frequency — the ranked order of the
unchanged matched set never changed (0/40 trials). The deterministic
corpus-growth flip proven by the checked-in ranking slice is a small-corpus
phenomenon; corpus dependence remains a disclosed property of ranked order,
not an observed event at these scales.
