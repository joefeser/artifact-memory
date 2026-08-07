# v0 resolver, vault, backup, and restore proof

Logical endpoint configuration is machine-local and remains outside portable
records. Resolution is authorization-gated and reports unavailable and
ambiguous endpoints explicitly.

Content registration writes immutable SHA-256 objects through a temporary file
and atomic rename. Re-registering identical bytes is a duplicate, not a new
version. The reference recovery path packages only allowlisted inputs,
encrypts the deterministic archive with an externally supplied passphrase,
records the encrypted and source-manifest digests, and verifies each restored
file in an empty isolated target. It does not activate restored state or grant
authority. Git bundle verification is a separate receipt.

The bound `restore_isolated` operation requires both the ciphertext digest and
the source-manifest digest from the corresponding backup receipt. It rejects an
unbound restore request. Before publishing the isolated target, it parses the
embedded manifest with duplicate-key rejection, verifies every allowlisted
entry, requires the embedded bytes to equal Artifact Memory canonical JSON for
that manifest, and compares the resulting digest with the expected
source-manifest digest. Semantically equivalent but non-canonical manifest
bytes therefore fail with `backup-manifest-noncanonical`; this is a v0
acceptance rule, not a global JSON requirement.
