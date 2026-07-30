# Foundation and Rewrite Concept

Status: design exploration  
Date: 2026-07-30

## Problem

People and software need to identify, locate, compare, exchange, and verify
files and knowledge even when paths, devices, operating systems, applications,
and storage providers change.

Git repositories preserve source and selected documentation, but product
meaning is often scattered across task conversations, research notes,
decisions, evidence, customer artifacts, and machine-local state. Copying an
entire tool-owned directory is neither a durable knowledge model nor a safe
publication boundary.

Artifact Memory separates knowledge, bytes, location, query views, and
recovery.

## Four layers

### Knowledge store

Versioned records describe people, interactions, decisions, questions,
concepts, workstreams, artifacts, provenance, claims, sensitivity, and
relationships. Records point to artifacts without embedding protected bytes or
credentials.

### Artifact vault

Private storage holds immutable originals, versions, derivatives, releases,
and evidence. A registered revision receives a new identity instead of
silently replacing an earlier version.

### Generated views

NDJSON, SQLite, HTML, search catalogs, relationship graphs, context packs, and
dossiers make records useful. They are derived from canonical records and can
always be rebuilt.

### Recovery store

Encrypted snapshots, Git bundles, content manifests, integrity checks, and
restore receipts protect the knowledge store and artifact vault. Recovery is
not the primary browse or recall mechanism.

## Identity model

```text
Artifact
  Stable semantic identity for something meaningful.

Artifact version
  Immutable revision, original, derivative, redaction, or release.

Content object
  Exact bytes identified by a named cryptographic digest and size.

Storage endpoint
  Logical storage authority, independent of a local mount point.

Location observation
  Evidence that content was present at a logical endpoint path at a time.

Manifest
  Deterministic inventory of a bounded logical tree or package.

Scan receipt
  Policy, scope, completeness, exclusions, errors, and manifest produced.

Knowledge record
  Meaning, claims, provenance, relationships, and artifact references.
```

An artifact URI is logical:

```text
artifact://example/artifacts/ART-0042/versions/1
```

It is not an original path, current mount point, download URL, or bearer token.
Machine-local resolver configuration may map the same endpoint to:

```text
macOS:   /Volumes/ArtifactVault
Windows: Z:\ArtifactVault
Linux:   /mnt/artifact-vault
```

## Canonical and generated data

Canonical records use portable JSON validated by versioned JSON Schemas.
Optional Markdown narratives may accompany structured records. Use one record
per file or record directory to keep Git diffs and merge boundaries useful.

Generated views include:

- `records.ndjson`;
- `records.sqlite`;
- HTML catalogs;
- search and relationship indexes;
- bounded agent context packs.

Every generated view identifies the exact source record-set digest used to
build it.

## Manifest requirements

A deterministic manifest specification must define:

- UTF-8 and Unicode normalization;
- separator and relative-path normalization;
- case-sensitive comparison and collision behavior;
- files, directories, symbolic links, hard links, sparse files, and platform
  metadata;
- exclusions and unreadable entries;
- partial-scan status;
- canonical serialization;
- root-digest calculation.

A container file hash and the hash of its normalized extracted tree are
different claims and must remain distinct.

## Extension model

Core records may carry namespaced extension objects:

```json
{
  "extensions": {
    "https://example.org/schemas/catalog/v1": {
      "catalogNumber": "SYNTHETIC-001"
    }
  }
}
```

Unknown optional extensions are preserved without interpretation. Unknown
required extensions fail closed. Extensions cannot redefine core identity,
digests, sensitivity, schema version, or authority.

Executable adapters declare capabilities separately. Records do not silently
carry executable logic.

Initial adapter categories are:

- scanners;
- storage resolvers;
- vault providers;
- transports;
- indexers;
- policy and sensitivity evaluators;
- context exporters.

## Exchange model

Two systems or agents can exchange a bounded record bundle without sharing
filesystem paths or implementation technology:

1. Sender builds a record bundle and deterministic manifest.
2. Sender declares schema versions, sensitivity, artifact references, and
   required capabilities.
3. Receiver validates structure, versions, integrity, and local policy.
4. Receiver admits, rejects, or quarantines each record.
5. Authorized artifact retrieval occurs through a resolver.
6. Receiver independently verifies content.
7. Receiver returns a receipt for admission, verification, indexing, and
   unresolved references.

Knowledge exchange does not grant execution, repository mutation, spending,
deployment, credentials, declassification, or acceptance of a claim.
Authority is a separate receiving-system contract.

## Historical lineage

The 2010 `WhereAreMyFiles` implementation used Windows filesystem metadata,
volume serial/name/size reconciliation, SHA-1 hashes, directory hierarchy, and
SQLite indexes. It recognized that drive letters change and that hashes,
metadata, and storage identity are separate evidence.

The rewrite modernizes that model:

| Historical concept | Artifact Memory concept |
| --- | --- |
| Drive information | Storage endpoint plus private resolver |
| Drive letter | Machine-local mount mapping |
| Volume identity heuristics | Endpoint discovery evidence |
| Directory information | Normalized manifest path |
| File information | Content object plus location observation |
| SHA-1 | SHA-256 with named algorithm |
| SQLite database | Generated query projection |
| Recursive scan | Platform-neutral scan receipt |
| ZIP/7z phase | Container and extracted-tree relationship |

## Non-goals for the first release

- Credential management.
- A hosted artifact service.
- A complete backup product.
- Automatic execution authority.
- Mutable bidirectional file synchronization.
- Private artifact storage in Git.
- A plugin marketplace.
- A broad user interface.

## Dogfood acceptance

The first private vault should store the reasoning and artifacts used to build
Artifact Memory itself. Success means:

- the records validate;
- the artifact content verifies;
- the same logical reference resolves under two mount layouts;
- SQLite can be deleted and rebuilt;
- an agent receives an authorized bounded context pack without vault access;
- encrypted backup restores into an isolated location;
- restored records and content pass independent digest verification.

