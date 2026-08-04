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
