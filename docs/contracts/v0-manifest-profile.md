# v0 normalized manifest profile

The supported v0 tree profile compares normalized relative paths
case-sensitively by Unicode code point, uses `/` separators, and hashes UTF-8
canonical leaf lines. Ordinary files and directories are supported. Symlinks,
special files, unreadable entries, and portability-affecting case-folded
collisions are explicit unsupported or partial outcomes.

When the host exposes a regular file as multiply linked or sparsely allocated,
the reference scanner returns an explicit unsupported failure and a partial
manifest instead of silently treating that physical semantic as an ordinary
file. Host detection coverage for those and other metadata remains evidence,
not a universal claim.

The normative tree algorithm sorts entries by normalized path in ascending
Unicode code-point order, serializes each directory as
`directory<TAB>{path}<LF>` and each file as
`file<TAB>{path}<TAB>{sha-256 content digest}<TAB>{byte size}<LF>`, concatenates
the UTF-8 lines without a header or trailing material beyond each line's LF,
and names the tree with the SHA-256 digest of those exact bytes. Mount roots,
host paths, filenames outside the normalized relative path, timestamps, and
enumeration order do not enter the digest.

`manifest_id` names the canonical manifest claim rather than only its tree.
Remove `manifest_id` and the derived `tree_digest` field, serialize the
remaining manifest object with the v0 canonical JSON profile, hash those bytes
with SHA-256, and prefix the lowercase hexadecimal digest with `manifest://`.
The canonical body therefore binds the schema, scan policy, comparison
profile, completeness state, normalized entries, and extensions; the separately
verified tree digest remains derivable from the entries.

Declared exclusions are policy and receipt evidence, not manifest entries.
Every excluded path remains separately accounted in the scan receipt; a scan
may remain complete only because its exact digest-bound policy declared that
scope reduction before metadata or content access. Unreadable or unsupported
in-scope entries instead make the manifest partial or failed.

Container bytes and an extracted tree are distinct content/tree claims even
when they describe related material. Unicode normalization, hard links, sparse
files, alternate data streams, extended attributes, and platform metadata are
not silently equated by this profile.

Manifest consumers fail closed unless entries are unique and sorted, paths are
normalized UTF-8 relative paths, every nested entry has an admitted directory
parent, file entries carry byte size and content digest, directory entries do
not carry file fields, and both manifest and tree identities match the
canonical body. Partial manifests remain useful bounded evidence, but a diff
that consumes one is explicitly partial.

Portable path components exclude ASCII control characters, backslashes,
Windows-forbidden characters (`<`, `>`, `:`, `"`, `|`, `?`, and `*`), trailing
dots or spaces, and case-insensitive Windows device names such as `CON`, `NUL`,
`COM1`, and `LPT1`, including those names before an extension. The semantic
validator enforces device-name exclusions that are intentionally not encoded
as a case-insensitive JSON Schema regular expression.

The checked `fixtures/synthetic/manifests/v1/` corpus contains two supported
logical trees represented under synthetic Windows, macOS, and Linux mount
layouts, plus executable collision, unsupported-link, and unreadable-partial
cases. The same receipt is replayed by CI on all three supported runner
families. This proves only the named ordinary-tree profile. Issue #24 owns
broader host-filesystem evidence for Unicode normalization, case behavior,
links, hard links, sparse files, alternate data streams, extended attributes,
timestamps, and mount layouts. Issue #25 owns archive extraction and the
container-to-extracted-tree relationship beyond keeping their identities
distinct.
