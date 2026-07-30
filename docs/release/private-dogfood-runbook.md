# Private dogfood and recovery runbook

This procedure is intentionally separate from the public repository. It must
be run only after the owner chooses an explicit private vault root, custody
endpoints, and key-recovery policy. No raw Codex transcript, attachment,
credential, browser state, or machine-local resolver configuration belongs in
the public repository.

## Bootstrap

1. Create an owner-controlled vault directory outside the repository with
   restrictive permissions.
2. Curate a small set of canonical records describing project direction,
   decisions, and public-source lineage. Use the authorized declassification
   and sensitivity policy before including any local task-derived material.
3. Register exact bytes through the content-addressed vault API; retain the
   registration receipt and verify duplicate behavior.
4. Project canonical records into NDJSON/SQLite views and delete/rebuild the
   generated views to prove they are not the durable store.
5. Export a bounded informational context pack and verify that it contains no
   unauthorized sensitivity or execution/route authority.

## Recovery

1. Allowlist only the vault and knowledge-store inputs for backup.
2. Supply the encryption passphrase through the owner-approved external key
   recovery mechanism; never put it in a record, fixture, command log, or Git.
3. Create and verify the encrypted backup and Git bundle.
4. Place any authorized off-machine copy under a separately recorded custody
   endpoint; an unobserved replica must remain an explicit limitation.
5. Restore into a new empty isolated directory, verify every manifest digest,
   and confirm that no active state, credential, session, or application
   database was overwritten.
6. Record the restore-test date, source manifest digest, backup digest,
   custody endpoint, key-recovery reference, and next test date in a private
   receipt. Publish only a sanitized receipt with no paths or private refs.

The public implementation proves the registration, encryption, Git-bundle,
and isolated-restore seams synthetically. It does not claim that this private
vault lifecycle has occurred until the owner-authorized run produces the
private receipts.
