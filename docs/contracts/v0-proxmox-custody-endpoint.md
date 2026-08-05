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
`config/templates/proxmox-restic-rest-server.v1.json`; the compatible SFTP
fallback remains `config/templates/proxmox-restic-sftp.v1.json`. Fill address,
account, repository, service, and ZFS policy values only after the VM is ready,
and keep secrets external to both the repository and Artifact Memory records.

This endpoint is off-machine custody on the same owner-controlled premises. It
must not be described as geographically off-site. A later physically separate
endpoint may add provider, geography, and jurisdiction diversity without
changing canonical records; no vendor, country, network, or identity provider
is mandatory at the portable contract boundary.
