# ADR 0015: Separate replayable benchmark invariants from runner measurements

Status: accepted for v0

## Decision

Artifact Memory benchmark receipts bind two kinds of evidence without
pretending they are interchangeable. Synthetic profile dimensions, corpus
identities, bounded outcomes, resource policy, structured claims, and
limitations are cross-run invariants. Each claim names its evidence fields,
binds the synthetic profile digest as provenance, and remains explicitly
`integrity-verified / issuer-unverified`. Wall time, throughput, SQLite size,
and traced Python allocation peaks are observations from one named runtime
family.

Checked conformance reruns the full synthetic profile and requires the
invariant projection to match. It validates the committed receipt identity and
human readback but does not require another machine to reproduce timing or
memory values exactly.

## Consequences

- Published baseline numbers remain descriptive rather than universal
  performance guarantees.
- A faster or slower CI runner does not invalidate deterministic corpus and
  fail-closed outcome evidence.
- Hostnames, absolute paths, accounts, and machine fingerprints never enter
  the receipt.
- Python traced allocation peaks explicitly exclude native and operating-system
  memory, so they cannot be represented as total process memory.
- A new profile or changed invariant requires new checked evidence; a timing
  observation alone cannot silently redefine the profile.
