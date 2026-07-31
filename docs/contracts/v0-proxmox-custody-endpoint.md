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

The initial transport is authenticated restic over SFTP, with encrypted
storage. Backups run after material vault changes and at least weekly; integrity
verification is monthly; isolated restore rehearsal is quarterly. Recovery
material remains separate from the workstation, repository, and backup VM.

The checked-in template deliberately contains no VM address, account,
storage path, or passphrase. Its provisioning state and remote-write state are
`owner-to-fill` and `not-authorized`; no remote write has been attempted.

The separate restic/SFTP configuration template is
`config/templates/proxmox-restic-sftp.v1.json`. It is an owner-local
configuration shape, not canonical knowledge; fill its address, account, and
repository only after the VM is ready, and keep secrets external to both the
repository and Artifact Memory records.
