# 0023: Gate projection reads on SQLite integrity verification

## Status

Accepted, 2026-08-27, for issue
<https://github.com/joefeser/artifact-memory/issues/105>.

## Context

Per-query tamper evidence validated the FTS5 content rows (`records_fts`)
against canonical record JSON but not the FTS5 inverted index
(`records_fts_data`). A two-step tamper — reindex a forged summary through
`records_fts`, then restore the original row in `records_fts_content`
directly — produced search results that passed full projection validation,
returned the authentic `source_record_set_digest`, and produced an equal
`logical_projection_snapshot`. An injected term matched and a real term was
silently dropped. The finding was independently reproduced on Python 3.14.4 /
SQLite 3.52.0 on 2026-08-27 and confirmed by an independent second opinion on
a fresh clone at `153f2843`.

Canonical records are versioned text and were never affected; the gap was in
tamper evidence for a generated, replaceable projection.

## Decision

- Every projection read now requires `PRAGMA integrity_check` to return `ok`
  inside `_read_index`, after contract validation and before yielding the
  read-only connection. Any other result, or a `sqlite3.Error`, maps to a
  typed `ValidationFailure("projection-unavailable", ...)`.
- Use the `PRAGMA` form, not the FTS5 `'integrity-check'` command form,
  because the command form is unusable on a read-only connection.
- Run the check last: content-row validation cannot observe the inverted
  index, so it must not be the final authority on search-row integrity.
- Reject runtimes whose `PRAGMA integrity_check` cannot verify FTS5
  (SQLite < 3.44) with `projection-unavailable`: on an incapable runtime an
  `ok` result is absence of evidence, not verification.
- Hold one read transaction across contract validation, integrity
  verification, and the caller's query, so a concurrent writer cannot commit
  tampering between check and use and the caller only ever sees the verified
  snapshot.
- The synthetic acceptance fixture is the two-step forgery itself: reindex
  through `records_fts`, restore `records_fts_content`, and require a typed
  failure from every query surface (search, related, provenance, metadata,
  logical snapshot).

## Compatibility

- Additive and fail-closed: indexes that are already physically inconsistent
  now return `projection-unavailable`; no schema, CLI, receipt, or output
  shape changes, and clean projections are unaffected.
- Read-only cost measured at roughly 0.1 ms per query at audit scale, beside
  existing per-query revalidation.
- Detection of inverted-index tamper depends on the runtime SQLite
  participating in `PRAGMA integrity_check` through FTS5 `xIntegrity`
  (SQLite >= 3.44; verified on 3.52.0). Runtimes below that floor fail
  closed rather than serving an unverifiable projection. The cross-SQLite
  matrix (issue #117) verified the behavior on 3.34.1 and 3.40.1 (fail
  closed, forgery never served) and on 3.46.1, 3.51.0, and 3.52.0 (forgery
  detected typed, clean reads served), with the gate-passing runtimes
  agreeing on source-record-set digests, logical projection snapshots, and
  default, literal, and ranked search results.
- Digest-bearing search receipts (issue #106) remain gated on this decision.

## Authority and limitations

The gate is informational tamper evidence for a generated view. It grants no
execution, mutation, spending, deployment, credential, declassification, or
approval authority, and it does not certify the truth of canonical records or
the absence of tampering in any copy not read through `_read_index`.

## Evidence

- GitHub issue: <https://github.com/joefeser/artifact-memory/issues/105>
- Contract: `docs/contracts/v0-filesystem-and-projections.md`
- Slice: `artifact_memory/projection_integrity_slice.py`, replayed by
  `python3 scripts/run_projection_integrity_slice.py --check` against
  `fixtures/synthetic/projection-integrity/v1/expected-receipt.json`
- Matrix: `python3 scripts/run_cross_sqlite_matrix.py` (issue #117), with
  observed runtime results recorded above
- Receipt schema:
  `artifact_memory/schemas/core/projection-integrity-slice-receipt.v1.schema.json`
- Unit fixture: `tests/test_projection.py`
  (`test_projection_queries_reject_fts_inverted_index_tampering`)
- End-to-end CLI receipt against the tampered fixture index:

  ```text
  $ python3 -m artifact_memory search <tampered-index> syntheticforged
  outcome: rejected
  diagnostics: [{'code': 'projection-unavailable', 'message': 'generated SQLite projection failed integrity verification'}]
  exit: 2
  ```
