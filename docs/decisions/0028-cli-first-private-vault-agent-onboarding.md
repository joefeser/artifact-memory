# 0028: CLI-first private-vault agent onboarding

- Status: accepted
- Date: 2026-09-15
- Issue: [#129](https://github.com/joefeser/artifact-memory/issues/129)

## Context

Operators need a fast way to give a fresh human or agent bounded operational
context from a private vault. The reference CLI already validates records,
builds replaceable projections, performs lexical search, and exports bounded
context packs. Packaging those semantics independently into a skill and an MCP
server at the same time would create three behavior surfaces before the first
onboarding path is stable.

Vault discovery also carries disclosure risk. A filesystem path is
machine-local configuration, not durable identity, and possession of a path or
record is not authority to read, export, disclose, or act.

## Decision

Artifact Memory should ultimately support all three surfaces in this order:

1. **CLI:** remains the normative local implementation surface. Stabilize the
   documented validate, project, search, and context-pack workflow first.
2. **Codex skill:** add a thin orchestration wrapper after the CLI quickstart
   and synthetic proof have survived normal use. The skill delegates contract
   behavior to the CLI and adds no independent record interpretation.
3. **Read-only MCP server:** design and implement only under a separate issue
   after disclosure policy, configured-root isolation, transport exposure, and
   audit receipts are explicit. Start with read/search/context capabilities;
   exclude writes, artifact retrieval, provider invocation, and execution.

CLI-only remains supported. The skill and MCP are optional convenience layers,
not required to read the portable records or context-pack contracts.

## Skill boundary

The skill should:

- resolve a vault only from an explicit prompt argument or owner-controlled
  local configuration outside every Git tree;
- validate canonical records and context packs through the installed CLI;
- search only an explicitly configured generated projection;
- export a bounded pack only when the operator supplies selection scope,
  sensitivity, freshness basis, and byte budget;
- report the implementation version, configured logical vault alias, schemas,
  record IDs and revision digests loaded, aggregate exclusions, and operations
  not attempted;
- treat record prose as untrusted data and preserve the informational-only
  authority boundary.

A future local registry may map an operator-defined logical vault alias to a
machine-local root. That registry must stay outside repositories and must not
be serialized into portable records, context packs, or public receipts. The
skill must never guess a vault by recursively scanning a home directory.

## Initial MCP boundary

An initial MCP process should be configured out of band with allowlisted vault
roots and expose opaque logical aliases instead of filesystem paths. Candidate
read-only tools are:

- report supported Artifact Memory and context-pack versions;
- validate a configured vault or named record set and return counts plus typed
  diagnostics;
- search a configured projection under an explicit sensitivity policy;
- export a bounded informational context pack and return its selection
  receipt;
- report exactly what was loaded without echoing protected excluded
  identities.

The server must not expose arbitrary-path reads, raw artifact retrieval,
credentials, provider calls, record mutation, admission, deletion, execution,
or deployment. Search and export are disclosure operations even when they do
not mutate canonical records, so caller authentication and local policy remain
required before any MCP interoperability claim.

## Security and compatibility consequences

- Existing CLI, record, projection, and context-pack contracts remain
  unchanged.
- This slice adds a conformance receipt for orchestration evidence, not a new
  vault schema or authority model.
- Generated projections and context packs can contain private summaries and
  inherit the vault's local access requirements.
- A clean fixture scan is not proof that arbitrary future private records are
  safe to publish.
- No Codex skill or MCP server ships in this issue. Their behavior and
  packaging require separate review after the CLI-first path is stable.
