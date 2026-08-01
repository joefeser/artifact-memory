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

## Authorized Codex-history derivative

1. The owner identifies exactly one local task and records selection authority
   in a private `codex-history-import-policy/v1`; do not use bulk discovery.
2. Curate only the allowlisted title, summary, decisions, research,
   workstreams, and open questions into a private task-export file. Never copy
   raw transcript rows or attachments into the import batch.
3. Set private or restricted sensitivity, an explicit raw-source expiry, the
   honest raw-retention mode, and the #36 correction and deletion routes. Do
   not claim encrypted recovery unless an encrypted raw archive actually exists.
4. Run `artifact-memory import-codex-history` with explicit local input files
   and a new private output directory. Review every draft record before
   accepting it into the canonical vault.
5. Keep the detailed declassification receipt private. Publish only the
   sanitized Codex-history dogfood receipt; verify it contains no task, record,
   content, digest, or location identifiers.
   Generate it with `artifact-memory codex-history-dogfood-receipt` from the
   private receipt and an explicit operation time.

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
