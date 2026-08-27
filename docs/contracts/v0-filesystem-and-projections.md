# v0 filesystem and projection seam

Status: normative minimum for the first executable slice

## Filesystem evidence

The reference scanner hashes regular files in streaming chunks and normalizes
relative separators to `/`. Entries are sorted by Unicode path order. The
tree digest is a SHA-256 over deterministic file and directory leaf lines; a
container or generated database digest is not a tree digest.

The v0 profile admits regular files and directories. Symlinks, special entries,
unreadable entries, and case-folded path collisions produce explicit partial
or unsupported diagnostics. A file that changes while being admitted produces
an explicit `unstable` diagnostic and contributes no content digest. Byte
limits are checked against a stable regular-file observation before any
file content is streamed, and hashing reads exactly that observed size.
Manifest admission validates schema, sorted unique normalized paths,
parent-directory coverage, file/directory field invariants, tree digest, and
manifest identity.
An unavailable, linked, or unsupported root is `failed`; an admitted root with
one or more bounded omissions remains `partial`.
Verification fails closed when the declared scan policy is not implemented by
the verifier; matching tree bytes do not authorize policy substitution.
The v2 scan receipt identifier covers its digest-bound policy, logical scope,
attempt bounds and times, implementation identity, manifest identity and tree
digest, outcome, exclusions, warnings, failures, counts, and compatibility
diagnostics, so distinct attempts and incomplete observations do not collapse
to one receipt identity. The complete normative rules are in
`v0-scan-policy-and-receipts.md`.

A diff validates both manifest identities before comparison. A partial,
failed, or cancelled input produces a partial diff whose diagnostic says that
only accounted entries were compared. It cannot silently become a complete
filesystem change claim. Inputs with different scan policies are rejected
rather than treated as comparable scopes. A moved candidate is a content/tree
match only; it does not prove semantic continuity, ownership, or source-language
meaning.

## Generated projections

Canonical knowledge records are sorted by `record_id` and serialized as
deterministic NDJSON. The source-record-set digest covers those canonical lines
and is stored in both the SQLite projection metadata and each record row.
SQLite includes versioned projection metadata plus indexed record, provenance,
relationship, and full-text views. Source record filesystem paths are not
stored. The normative generated schema is packaged as
`artifact_memory/schemas/core/index-sqlite.v1.sql`; the runtime rejects a
resource whose `user_version` does not match its supported projection version.
SQLite, NDJSON, and their receipts are generated views; deleting all
of them and rebuilding from canonical records must produce equivalent logical
rows, query results, canonical NDJSON, and source-record-set identity. SQLite
file bytes themselves are not canonical identity.
Query commands open SQLite projections read-only. A missing or malformed index
returns `projection-unavailable` and must not create a replacement database.
Every query first verifies the SQLite user version, projection schema identity,
required columns and indexes, metadata cardinality and types, source-set
digest consistency, record count, and provenance ordinals. Every query then
requires `PRAGMA integrity_check` to return `ok`, so an index whose FTS5
inverted index disagrees with its content rows — for example a summary
reindexed through `records_fts` and then restored in `records_fts_content` —
returns `projection-unavailable` instead of serving forged terms that pass
content-row validation. A runtime whose integrity check cannot reach the FTS5
inverted index (SQLite older than 3.44) also returns `projection-unavailable`
rather than trusting an unverifiable `ok`, and validation plus the query run
inside one read transaction so the caller sees exactly the verified snapshot.
An incompatible
version or schema identity returns `projection-schema-mismatch`; malformed FTS
syntax remains a distinct `query-invalid` caller outcome.

A `search-receipt` command beside raw `search` returns the SHA-256 digest of
the exact UTF-8 query bytes, matched record IDs, the projection's
`source_record_set_digest`, and the integrity-gate outcome
(`artifact-memory/search-receipt/v1`), pinning query evidence to the exact
canonical record set that produced the index. The receipt never echoes the raw
query. Its unkeyed digest prevents direct logging but does not conceal a
guessable low-entropy query from dictionary inference. Because the receipt is
issued inside the gated read, a tampered index yields a typed failure instead
of a vouched receipt. The raw `search` output and every existing receipt keep
their shapes.

Projections do not copy credentials, resolver configuration, protected bytes,
TraceMap provider schemas, WITS memory cards, HACP Task Packets, Route Tasks,
Codex continuation payloads, or authority. A context pack will consume these
canonical records later as informational output only.

The checked-in `fixtures/synthetic/scan-projection/v1` receipt proves this seam
end to end. Replay it with:

```sh
python3 scripts/run_scan_projection_slice.py --check
```

The checked-in `fixtures/synthetic/projection-integrity/v1` receipt proves the
read integrity gate end to end, including the two-step inverted-index forgery.
Replay it with:

```sh
python3 scripts/run_projection_integrity_slice.py --check
```

The checked-in `fixtures/synthetic/search-receipt/v1` receipt proves the
digest-bearing search receipt end to end, from canonical records through the
CLI receipt. Replay it with:

```sh
python3 scripts/run_search_receipt_slice.py --check
```
