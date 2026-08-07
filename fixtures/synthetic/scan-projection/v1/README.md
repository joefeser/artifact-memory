# Provider-free scan and projection proof

This entirely synthetic fixture proves the #15 and #17 seam without a
provider, private vault, machine-local path, resolver configuration, or
authority-bearing packet.

`before/` and `after/` exercise a changed file, an added file, and an exact
content move candidate. `records/` exercises deterministic NDJSON, SQLite
metadata, full-text search, relationships, and provenance queries.

Run:

```sh
python3 scripts/run_scan_projection_slice.py --check
```

The runner scans and verifies both trees, emits a content/tree-only diff,
projects the canonical records in two input orders, queries the generated
views, deletes every generated view, rebuilds them from canonical records,
and compares the logical results. SQLite file bytes remain replaceable and
are never canonical identity. A move candidate does not prove semantic
continuity.
