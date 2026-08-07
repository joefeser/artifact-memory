# Approved Proxmox custody endpoint template

The approved first off-machine custody target is a dedicated guest VM on Joe's
Proxmox server. Tailscale belongs inside that guest only; it must never be
installed on the Proxmox host. The guest exposes no public inbound service and
accepts authenticated backup traffic only from approved tailnet clients.

The portable logical identity is
`endpoint://joe-home-proxmox-vault-1`. Canonical records and receipts must not
use the VM hostname, IP address, mount point, drive letter, or UNC path as
identity. Those values belong only in owner-controlled local resolver or
transport configuration after the VM is provisioned.

The v2 endpoint contract prefers authenticated restic through `rest-server` in
append-only mode. Restricted SFTP with a dedicated non-root account remains the
fallback profile. Both profiles use client-side restic encryption and mandatory
ZFS-backed storage with a separately controlled scheduled snapshot policy.
Append-only admission limits destructive backup-client access; ZFS snapshots
provide a separate rollback boundary and do not replace restic integrity checks
or restore rehearsal.

## Contract evolution

Consumers must select a parser from the exact `schema_id` before interpreting
any other field. A v1-only reader must reject
`artifact-memory/custody-endpoint/v2`; it must not attempt to parse a v2
document as the v1 shape. Transforming a v1 document into v2 is an explicit
migration that creates and validates a new document rather than silently
relabeling the old one:

- v1 `transport.method: restic-over-sftp` maps to the declared v2
  `transport.fallback`; v2 adds `transport.primary` for append-only
  `restic-rest-server` and its address, account, repository, and service states;
- v1 `storage.encryption` maps to v2 `storage.client_side_encryption`; v2 also
  requires the ZFS backend, snapshot policy, snapshot control, and schedule
  states; and
- v1 provisioning fields carry forward, while v2 adds the snapshot-schedule
  state and the additional recovery and diversity boundaries.

There is no automatic downgrade from the v2 primary to its fallback. If the
primary cannot satisfy the v2 authorization gate, the v2 endpoint remains
`not-authorized`, and a still-supported SFTP-only endpoint remains a v1
document. After the primary and overall endpoint are configured and authorized,
an owner-local resolver may select the configured fallback only when the
primary is temporarily unavailable. Declaring the fallback never authorizes it,
and selection does not change endpoint identity or expand write authority.

The reference runtime exposes
`migrate_custody_endpoint_v1_to_v2(document)` for that explicit migration. It
accepts only an exact, valid v1 document, builds a separate v2 object with
fail-closed defaults for every v2-only state, validates the result, and rejects
v2 input or relabel-only conversion.

Before any future remote-write implementation consumes these contracts, it
must call `validate_custody_write_preflight(endpoint, adapter)`. That seam
dispatches on the exact rest-server or SFTP adapter schema, validates both
documents, binds their logical endpoint, authorization,
connection-readiness, service, and snapshot states, and rejects any mismatch.
Its deterministic receipt binds canonical endpoint, adapter, and compared-state
digests. It is evidence only: it attempts no connection or write,
contains no connection details or secrets, and never substitutes for explicit
owner authorization.

Backups run after material vault changes and at least weekly; integrity
verification is monthly; isolated restore rehearsal is quarterly. Recovery
material remains separate from the workstation, repository, and backup VM. A
console or local recovery path must remain available and may not depend
exclusively on Tailscale.

The checked-in templates deliberately contain no VM address, account, storage
path, passphrase, or private recovery material. Provisioning and remote-write
states remain `owner-to-fill` and `not-authorized`; no remote write has been
attempted. The v2 schema fails closed if a document claims an authorized write
before the VM, account, repository, storage, service, and snapshot schedule are
all configured.

The preferred owner-local configuration shape is
`config/templates/proxmox-restic-rest-server.v1.json`; the current SFTP
fallback is `config/templates/proxmox-restic-sftp.v2.json`. The v1 SFTP shape
remains valid and fail-closed for compatibility but cannot authorize a write;
v2 adds the restricted non-root mode and ZFS snapshot boundary. Fill address,
account, repository, service, and ZFS policy values only after the VM is ready,
and keep secrets external to both the repository and Artifact Memory records.

Checked-in deterministic evidence covers the rest-server v1, SFTP v1, and SFTP
v2 preflight paths under `fixtures/synthetic/custody-preflight`. The exact v1 to
v2 endpoint migration output and its human-readable receipt are pinned under
`fixtures/synthetic/custody-endpoint/v2`. These synthetic receipts prove
contract behavior only; they do not prove provisioning, connectivity, custody
transfer, credentials, or remote-write authority.

The first real-operation public summary is a separate external owner
attestation. Its authoritative machine-readable form is
`evidence/sanitized/custody/v1/receipt.json`, validated by
`artifact-memory/sanitized-custody-attestation/v2`; `receipt.md` is a generated,
byte-checked projection. This proves only that the public artifact conforms to
the versioned shape and privacy boundary. It does not independently replay or
verify the private backup and restore operations. The machine receipt therefore
labels the claim `owner-attested/issuer-unverified`, records that its private
evidence binding is withheld under owner control, and states that independent
replay is false. No public digest is presented as a substitute for access to or
verification of the private evidence.

Historical safety scanning preserves only the known pre-contract v0 Markdown
shape already present in repository history: the `Endpoint` field, either LF or
CRLF line endings, and the earlier explanatory `endpoint://` prose. That shape
is normalized only for privacy scanning; it is not silently reinterpreted as a
v1 machine attestation. Unknown historical shapes fail closed and require an
explicit compatibility rule or versioned migration before public-readiness
scanning can pass.

The two v1 JSON shapes already present in this PR's public Git history are also
handled explicitly: the exact pre-provenance shape is pinned by a compatibility
schema, and the later provenance-bearing v1 shape remains under the core v1
schema. New attestations use v2. Historical dispatch rejects duplicate keys,
unknown schema identifiers, schema drift, and endpoint changes before applying
the same machine-binding scan used for current content.

This endpoint is off-machine custody on the same owner-controlled premises. It
must not be described as geographically off-site. A later physically separate
endpoint may add provider, geography, and jurisdiction diversity without
changing canonical records; no vendor, country, network, or identity provider
is mandatory at the portable contract boundary.
