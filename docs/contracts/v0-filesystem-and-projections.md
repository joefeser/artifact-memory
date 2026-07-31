# v0 filesystem and projection seam

Status: normative minimum for the first executable slice

## Filesystem evidence

The reference scanner hashes regular files in streaming chunks and normalizes
relative separators to `/`. Entries are sorted by Unicode path order. The
tree digest is a SHA-256 over deterministic file and directory leaf lines; a
container or generated database digest is not a tree digest.

The v0 profile admits regular files and directories. Symlinks, special entries,
unreadable entries, and case-folded path collisions produce explicit partial
or unsupported diagnostics. A moved candidate is a content/tree match only;
it does not prove semantic continuity, ownership, or source-language meaning.

## Generated projections

Canonical knowledge records are sorted by `record_id` and serialized as
deterministic NDJSON. The source-record-set digest covers those canonical lines
and is stored in the SQLite projection. SQLite, FTS, and relationship tables
are generated views; deleting them and rebuilding from canonical records is
expected to produce equivalent logical results.

Projections do not copy credentials, resolver configuration, protected bytes,
TraceMap provider schemas, WITS memory cards, HACP Task Packets, Route Tasks,
Codex continuation payloads, or authority. A context pack will consume these
canonical records later as informational output only.
