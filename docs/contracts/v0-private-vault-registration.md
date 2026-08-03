# v0 private vault registration

Vault intake accepts exact bytes plus explicit portable artifact metadata. It
does not derive identity from a filename, source path, hostname, or mount
layout. The SHA-256 content identity, logical artifact identity, and immutable
artifact-version identity remain distinct.

When an expected digest is supplied and does not match, bytes are stored only
in the vault's quarantine area and no canonical artifact or version record is
created. Valid intake registers content through an atomic temporary-file write,
verifies the stored bytes, validates canonical artifact and version records,
and writes those records as versioned text. Exact replay is a duplicate;
conflicting immutable records fail closed.

Publication prefers atomic no-clobber hard links. A filesystem that does not
support hard links uses a same-directory publication lock and atomic replace;
all Artifact Memory writers honor that lock. Cleanup failures and mixed
canonical-record recovery states are explicit failures that require inspection
or replay, never successful registration.

Interrupted object finalization emits a failed registration receipt and cleans
the partial file. Canonical record writes are independently replay-safe; a
failed multi-record intake may leave already-verified immutable content but
cannot reinterpret or overwrite it.

Receipts disclose portable identities, outcomes, and diagnostics only. They
contain no local path or private material and grant no authority.
