# Sanitized first off-machine custody receipt

- Attester role: `repository-owner`
- Attestation status: `owner-attested/issuer-unverified`
- Private evidence binding: `withheld-owner-controlled`
- Independent replay: `false`
- Observed: `2026-08-06`
- Endpoint: `endpoint://joe-home-proxmox-vault-1`
- Custody claim: `off-machine-not-geographically-off-site`
- Transport profile: encrypted restic through the restricted SFTP fallback
- Backup input: explicit private-vault and knowledge-store allowlist
- Remote write: one non-empty snapshot completed
- Repository verification: every stored data blob was read without error
- Restore: the exact remote snapshot restored into a new isolated target
- Restored verification: ten allowlisted source files matched the private manifest; four canonical artifact/version records validated; two content objects matched their digests; the restored Git bundle verified
- Storage boundary: ZFS-backed repository with a separately controlled weekly snapshot timer and bounded retention; a manual server-controlled post-write snapshot succeeded after the first remote backup
- Recovery cadence: monthly restic integrity verification and quarterly isolated restore rehearsal
- Private material committed: `false`

The private evidence retains exact snapshot, manifest, backup, restore, and
machine-local bindings, including validated private receipts where the
published contracts apply. This sanitized receipt intentionally contains no
network address, VM hostname, account, path, repository identifier, content
digest, task identifier, credential, passphrase, or recovery reference. The
published logical endpoint value is a portable identity, not a network
hostname or address.

This proof establishes one encrypted off-machine copy and one successful
isolated restore on the same owner-controlled premises. It does not establish
geographic off-site protection, append-only transport, global erasure, source
authenticity, future recoverability, or execution, disclosure, routing, merge,
or deployment authority. Recovery material remains owner-controlled and was
not inspected by the agent.
