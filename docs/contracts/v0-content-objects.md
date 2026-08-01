# v0 exact-content identity and verification

Status: normative for `artifact-memory/content-object/v2`

A content object describes exact bytes without using a filename, timestamp,
path, endpoint, mount, or custody location as equality evidence. V0 content
identity uses SHA-256. For a supported object, `content_id` is
`content://sha-256/<lowercase-hex>` and the `digest` field is
`sha-256:<same-lowercase-hex>`.

The primary digest is the identity claim. Optional `secondary_digests` are
additional integrity claims, not alternate identities. Each algorithm may
appear once. A verifier checks all declared digests. V0 implements SHA-256 and
SHA-512; an unknown declared algorithm produces `unsupported`, not success.
Malformed known digests or a SHA-256 `content_id` that disagrees with `digest`
are invalid contracts rather than byte mismatches.

Verification streams bytes and returns one of:

- `verified`: size and every declared digest match;
- `mismatch`: observed size or any supported digest differs;
- `unreadable`: bytes could not be read, with no claim of absence; or
- `unsupported`: at least one declared digest algorithm cannot be checked.

Receipts never record the machine-local input path. Verification establishes
integrity only; it grants no execution, disclosure, mutation, authenticity,
trust, or authorization.

The language-neutral recipes under `fixtures/synthetic/content/v1/` include a
zero-byte object and a deterministic 5 MiB object without committing a large
binary. Any implementation can reproduce a recipe by repeating the named byte
for the declared count.
