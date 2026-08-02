# ADR 0013: Bind portable tree identity to a narrow ordinary-tree profile

- Status: Accepted
- Date: 2026-08-02
- Issues: #6, #24, #25
- Discussion: #30

## Context

Windows, macOS, and Linux can disagree about separators, case behavior,
Unicode names, links, sparse files, alternate data streams, extended
attributes, timestamps, and mount layouts. A digest that silently imports host
semantics would overclaim equivalence and make independent implementations
non-interoperable.

## Decision

V0 admits ordinary files and directories whose names are normalized portable
UTF-8 relative paths. Entries compare case-sensitively by Unicode code point,
sort by normalized path, and use the exact UTF-8 leaf serialization specified
in `docs/contracts/v0-manifest-profile.md`. SHA-256 names the concatenated leaf
bytes. Mount roots, enumeration order, timestamps, and host metadata do not
enter tree identity.

The manifest ID remains a separate canonical claim over schema, policy,
comparison profile, completeness, entries, and extensions. Container bytes
remain a separate content identity from any extracted-tree digest.

Case-folded collisions, links, special files, unreadable entries, and other
unproven semantics produce explicit collision, unsupported, or partial
evidence. They do not inherit ordinary-tree equivalence.

## Alternatives considered

- Normalizing every Unicode name was rejected because filesystems do not expose
  one universally evidenced normalization behavior.
- Including timestamps or platform metadata was rejected because it makes the
  same logical content depend on observation environment.
- Following links or flattening hard links was rejected because target and
  alias semantics are not portable or safely implied.
- Treating an archive digest as its extracted tree was rejected because
  container bytes and extraction behavior are distinct claims.
- A broad Merkle node format was deferred because the small sorted-leaf profile
  is sufficient for the first executable slice and easier to reproduce
  independently.

## Consequences

The checked manifest fixture carries two positive equivalent-tree cases across
three synthetic mount layouts, executable collision/unsupported/partial cases,
and a distinct container/tree example. CI replays the same receipt on macOS,
Ubuntu, and Windows.

Issue #24 remains the follow-up for broader evidence from actual filesystem
semantics, including Unicode, case, links, hard links, sparse files, alternate
data streams, extended attributes, timestamps, and mount behavior. Issue #25
remains the follow-up for safe archive extraction and richer
container-to-extracted-tree relationships.
