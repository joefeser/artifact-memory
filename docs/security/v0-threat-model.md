# Artifact Memory v0 threat and declassification boundary

Status: accepted
Date: 2026-07-30
Linked issues: #3, #2, #35, #36, #37

## Scope

This model covers public contracts, synthetic fixtures, local adapters,
exchange bundles, generated views, private vault boundaries, and the eventual
dogfood workflow. It does not authorize a hosted service, credential store,
automatic synchronization, or autonomous execution.

## Assets and actors

| Asset | Examples | Required protection |
| --- | --- | --- |
| Meaning | Decisions, claims, provenance, relationships | Integrity, sensitivity, bounded disclosure |
| Artifact identity | Semantic artifact and version identifiers | Stability without path leakage |
| Content bytes | Originals, derivatives, evidence | Integrity, custody, access policy |
| Location evidence | Endpoint and observation records | No durable machine-local paths |
| Generated views | NDJSON, SQLite, context packs | Rebuildability and source-set provenance |
| Receipts | Scan, admission, verification, restore outcomes | Honest completeness and failure state |
| Recovery material | Encrypted archives and Git bundles | Separate custody and key-recovery policy |

Actors are the record author, an authorized local operator, an exchange sender,
an exchange receiver, a malicious or compromised sender, a malicious record,
an adapter process, a storage provider, and an accidental public contributor.
The receiver and operator are not assumed to be the same principal.

## Trust boundaries

1. **Public repository / private vault:** the repository contains only
   public-safe contracts, code, synthetic fixtures, and receipts newly authored
   from public-safe synthetic inputs. Sanitizing or redacting a private
   operational receipt does not make it publishable. Real records, bytes, task
   archives, sessions, and resolver configuration remain outside it.
2. **Canonical records / generated views:** canonical JSON is authoritative;
   indexes and context packs are replaceable projections with source-set
   digests.
3. **Record validation / claim truth:** schema validity and digest integrity do
   not establish provenance truth, signer trust, authorization, or custody.
4. **Exchange / authority:** receiving a record or envelope does not authorize
   retrieval, execution, mutation, disclosure, spending, deployment, or
   approval.
5. **Adapter / host:** adapter capabilities and permissions are declared and
   independently authorized by the host; record contents cannot grant them.
6. **Active state / recovery state:** restore occurs into isolation and cannot
   overwrite active state without a separately authorized operation.

## Abuse cases and controls

| Abuse case | Control | Honest residual behavior |
| --- | --- | --- |
| Secret, bearer material, or private record enters a fixture | Allowlist-based synthetic fixture policy; local/CI history and path checks | A clean scan is not proof of absence; visibility change requires a separate audit |
| Absolute path or mount leaks machine state | Logical endpoints and relative observations only | Resolver configuration remains local and unportable |
| Malicious record smuggles executable authority | Reject authority-bearing record semantics; host authorizes adapters separately | Unsupported or unauthorized operations return explicit failure receipts |
| Schema bomb or oversized payload exhausts resources | Bounded parsing, size/depth limits, and resource receipts as implementations arrive | Cancellation and limits remain distinct from successful validation |
| Tampered bytes or manifest | Named digests, deterministic manifests, and independent verification | Integrity does not imply authenticity or trusted claims |
| Replay or contradictory receipt | Correlation, provenance, idempotency, and explicit contradiction outcomes | Receiver may quarantine rather than silently merge |
| Accidental ingestion or deletion request | Retention, redaction, tombstone, and deletion receipts from #36 | Destructive deletion is separately authorized and backup limits stay visible |
| Raw Codex task history is bulk-ingested | Explicit task selection, field allowlist, redaction, and provenance from #37 | Raw archives remain recovery evidence, not canonical knowledge |

## Public fixture allowlist

Allowed fixture material is newly authored synthetic data containing only:

- synthetic identifiers, claims, paths, endpoint aliases, digests, timestamps,
  and receipt outcomes;
- deliberately invalid records whose expected result is rejection;
- small deterministic byte descriptions or generated test bytes;
- no real names, customer material, private strategy, raw conversations,
  attachments, credentials, cookies, tokens, browser state, or machine-local
  resolver configuration.

Redaction of real material is not a fixture-generation method. Unknown optional
extensions may be present as opaque synthetic values; unknown required
extensions must produce a fail-closed result.

## Logging and receipts

Logs and receipts contain operation identity, source-set or input digest,
implementation identity, policy identity, timestamps, outcome, completeness,
warnings, failures, and nonclaims. They must not echo bearer values, raw
secrets, private bytes, or local resolver credentials. Secret-like findings
report only safe location/object metadata, never the matched line.

## Declassification rule

No record, digest, receipt, context pack, backup, or exchange envelope
declassifies protected material. Publication, disclosure, restoration into an
active environment, and destructive deletion each require a separate policy
decision and authorization outside the data record itself.
