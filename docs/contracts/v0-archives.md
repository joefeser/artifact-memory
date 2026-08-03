# V0 archive and extracted-tree boundary

V0 supports bounded, read-only ZIP inspection. An archive container is an exact
content object whose SHA-256 digest covers the ZIP bytes. A complete safe
inspection produces a separate normalized extracted-tree manifest digest and a
`container-extracts-to-tree` relationship binding the two identities. Equality
of either digest never implies equality of the other.

Inspection reads entry bytes in memory only. It does not extract to the
filesystem, follow links, execute content, mutate the container, disclose
content, or establish authenticity or trust.

## Outcomes and completeness

| Outcome | Meaning | Extracted-tree relationship |
| --- | --- | --- |
| `supported` | Every observed entry is within the v0 ZIP profile and all entry bytes verify within configured bounds. | Required; completeness is `complete`. |
| `partial` | The container is readable, but one or more entries are unsafe, colliding, corrupt, or outside a resource bound. Accepted entries are observations only. | Forbidden; completeness is `partial`. |
| `unsupported` | The readable container has no accepted files and depends only on unsupported entry features such as links, encryption, entry kinds, or compression. | Forbidden; completeness is `unavailable`. |
| `failed` | Container bytes are unavailable or the ZIP central directory is invalid. | Forbidden; completeness is `unavailable`. |

A partial receipt carries an `observed_entry_set_digest`, not a complete tree
identity. It must never be upgraded into an extracted-tree manifest claim.
When container bytes cannot be read, their digest and size are `null`; the
implementation does not fabricate an all-zero content identity. A malformed but
readable byte sequence retains its independently computed container digest even
when ZIP inspection fails.

## Entry safety

Entry names are normalized to `/` separators before comparison. Absolute,
drive-qualified, empty-segment, `.`-segment, `..`-segment, and NUL-containing
paths produce `path-traversal`. Exact normalized repeats produce
`duplicate-entry`; distinct names colliding under Unicode case folding produce
`case-collision`.

ZIP symbolic links and other special entry kinds are never opened. Encrypted
entries and unsupported compression methods are explicit unsupported evidence.
CRC/read failures produce `corrupt-entry`. Declared uncompressed bytes and entry
count are bounded before content is admitted; crossing a bound produces
`decompression-limit` or `entry-count-limit`. Processing stops at a resource
limit and does not imply that later entries were inspected.

The profile does not claim portable handling for permissions, ownership,
timestamps, extended attributes, sparse extents, hard links, device entries,
Unicode normalization aliases, nested archives, or arbitrary archive formats.

## Receipt verification

The v2 receipt binds its canonical body, sorted unique accepted entries, entry
set digest, complete extracted-tree manifest digest, and container/tree
relationship. `validate_archive_receipt` checks those semantic bindings after
schema validation. Container byte verification remains a separate comparison
against the named container digest. The reference inspector hashes the same open
file before and after inspection; a changed stream fails without retaining a
container or tree identity claim.

`archive-receipt/v1` is retained only so historical inputs can be recognized and
schema-checked. The reference inspector emits v2 exclusively. A valid v1 receipt
passed to `validate_archive_receipt` fails with the typed
`archive-receipt-migration-required` outcome: v1 lacks the completeness,
unavailable-container, entry-set, and explicit container/tree bindings required
for a safe automatic conversion. Consumers must re-inspect the named container
bytes to produce v2 evidence; they must not relabel or mechanically upgrade a v1
receipt. This is an explicit migration boundary, not transparent v1 support.

Both the top-level `entries` and extracted-tree manifest publish the same closed
file-entry shape. Entries are unique and sorted lexicographically by normalized
`path`; paths must also satisfy the safety and collision rules above. JSON Schema
enforces each item shape. Ordering, unique paths, exact manifest equality, and
cross-entry path conflicts are semantic constraints enforced by
`validate_archive_receipt`; the v0 schema subset cannot express those comparisons.

## Checked synthetic evidence

`fixtures/synthetic/archives/v1/vectors.json` is a newly authored recipe set. It
deterministically creates temporary safe, traversal, duplicate, case-collision,
link, encrypted-flag, corrupt-CRC, and decompression-limit ZIP cases. No binary
or historical archive is copied into the repository.

```sh
python3 scripts/run_archive_conformance.py --check
```
