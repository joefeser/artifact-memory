# Import a private session ledger

AM-1 converts a bounded Markdown done log into deterministic draft knowledge
records in a private vault. It does not create WorkReceipts, TaskPackets, task
completion, or authority: an unstructured ledger cannot supply those strict
coordination bindings honestly.

The source format is intentionally small. Blank lines and Markdown headings
are allowed. Every other line is one entry beginning with a valid ISO calendar
date, optionally preceded by a Markdown bullet and optionally followed by a
colon or hyphen:

```markdown
# Done log

- 2026-09-25: Verified the synthetic adapter.
2026-09-26 Added bounded startup context.
```

Preview the mapping without creating the vault or writing records:

```bash
artifact-memory import-session-ledger done-log.md --vault "$ARTIFACT_MEMORY_VAULT" --dry-run --json
```

Apply the import:

```bash
artifact-memory import-session-ledger done-log.md --vault "$ARTIFACT_MEMORY_VAULT" --json
```

Each entry becomes one `artifact-memory/knowledge-record/v3` draft under
`records/session-ledger/`. Identity is deterministic from the normalized date,
summary, and duplicate occurrence number, so replay reuses byte-identical
records. The record carries private sensitivity and import provenance with the
exact source reference `session-ledger`. The source filename, path, and raw log
are not copied into the vault or printed in the dry-run mapping.

The importer accepts at most one MiB, 1,000 entries, and 4,096 normalized
characters per entry. Invalid dates, undated content, credential-like material,
unsafe storage paths, and immutable-path collisions fail typed. Credentials
belong in an approved secret manager, never a memory record. Common assignment
forms are rejected whether names use spaces, hyphens, or underscores, including
API keys, client secrets, access or refresh tokens, and secret access keys.
GitHub token assignment names and recognized GitHub token prefixes are rejected
as credential-like material as well.
Before publishing any record, the importer preflights the complete batch under
a vault-local lock; a collision in a later entry therefore cannot publish an
earlier entry. Imported records remain informational and require separate owner
review and authenticated authority before any action.
