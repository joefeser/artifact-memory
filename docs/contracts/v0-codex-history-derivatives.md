# V0 authorized Codex-history derivatives

Status: executable contract candidate
Decision: `docs/decisions/0006-local-codex-history-intake.md`
Linked issues: #37, #3, #4, #8, #20, #36

Artifact Memory may transform one explicitly selected local Codex task into
curated, vendor-neutral draft records. Raw Codex storage is neither a canonical
store nor an implicit source of truth. Intake is local-only, owner-authorized,
bounded to one task, and driven by an explicit allowlist.

## Selection and intake

The operator creates an
`artifact-memory/codex-history-import-policy/v1` outside the public repository.
It names exactly one portable task identifier, an owner authority reference,
authorization time, record sensitivity, raw-source expiry, and #36 correction
and deletion routes. It states whether the source stays source-system managed
until expiry or is retained only as encrypted recovery evidence.
`bulk_ingestion` and `network_access` are always false.
For a real local task, initial derivatives must remain `private` or
`restricted`; publication requires a later, separate declassification decision.

The selected task is represented as one local task-export object. The only
fields eligible for interpretation are:

- `task_id`, `title`, and `summary`;
- curated `decisions`, `research`, and `workstreams`;
- curated `open_questions`.

Every field has type, item-count, and text-size bounds. Allowlisted text that
contains an absolute path or a high-confidence credential pattern fails closed.
These checks are guardrails, not proof that arbitrary prose is safe. Owner
review remains required.

Raw transcript rows, attachments, credential material, browser state,
machine-local paths, unrelated task content, and unrecognized source fields are
never copied into the output batch. The CLI accepts explicit local files and
has no discovery, network, or bulk-ingestion path. It writes only to a newly
created output directory, so it cannot silently replace an existing import.

## Derivative records and provenance

The v2 transformer emits separate `knowledge-record/v2` drafts for:

- decisions (`record_type: decision`);
- research summaries (`record_type: note`, label `research`);
- workstream state (`record_type: workstream`);
- open questions (`record_type: question`).

Each record retains a private `codex-task://local/...` source reference,
`artifact-memory/codex-history-allowlist/v2` transformation provenance, an
explicit uncertainty statement, and private or restricted sensitivity. The
records contain source-neutral meaning; the provider reference remains
provenance rather than canonical identity for the meaning itself. They remain
draft until the owner reviews and accepts them.

`artifact-memory/declassification-receipt/v2` identifies admitted fields and
records without repeating excluded values, aligns each unique record identity
with its class, and records per-class counts. Consumers verify its digest-bound
identity before using those claims; this proves integrity, not issuer
authenticity or trust. It records the raw-source retention policy and expiry,
states that raw history is non-canonical, and routes correction through record
supersession and deletion through the #36 retention/deletion contract. A
deletion request is informational and cannot execute deletion.

## Raw-source lifecycle

The importer does not copy raw history into Artifact Memory. The original may
remain source-system managed until the explicit expiry. If the owner separately
retains a raw archive under Artifact Memory custody, that archive must be
encrypted recovery evidence under an owner-controlled policy. Neither form is
copied into canonical records or generated indexes. Expiry does not itself
delete bytes: removal requires separate owner authorization and endpoint-scoped
#36 receipts. Corrections create a new record identity and preserve the earlier
record as superseded history; correction is not deletion. Unknown replicas
remain explicit.

## Public/private boundary

The real task export, import policy, derivative records, source references,
declassification receipt, generated views, and output location stay outside
GitHub. After a successful owner-reviewed dogfood run, the repository may
contain only an `artifact-memory/codex-history-dogfood-receipt/v1`. That
sanitized receipt reports the operation time, outcome, counts, and nonclaims;
it contains no source-task identity, private digest, record identity, content,
or location.

The synthetic conformance fixture is newly authored and exercises import,
record validation, projection rebuild, bounded informational context export,
and a non-authorizing deletion request. It is not derived from real task
history and does not prove the private dogfood run occurred.

## Local operator flow

With owner-selected files and a new private output directory:

```sh
artifact-memory import-codex-history \
  "$AM_CODEX_TASK_EXPORT" \
  "$AM_CODEX_IMPORT_POLICY" \
  --out "$AM_CODEX_IMPORT_BATCH" \
  --json
```

The command prints only counts, outcome, owner-review requirement, and the
no-authority boundary. It does not print task identity, record identities,
input paths, or output paths.

After the owner validates and retains the detailed receipt privately, the
public-safe receipt is generated from that private receipt without echoing its
identity-bearing fields:

```sh
artifact-memory codex-history-dogfood-receipt \
  "$AM_CODEX_PRIVATE_DECLASSIFICATION_RECEIPT" \
  --performed-at "$AM_CODEX_IMPORT_TIME" \
  --json
```
