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
