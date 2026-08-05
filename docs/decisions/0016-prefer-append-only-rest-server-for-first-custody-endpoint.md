# Prefer append-only rest-server for the first custody endpoint

## Decision

The first approved off-machine endpoint uses a dedicated Proxmox guest with
ZFS-backed storage. The preferred transport profile is authenticated restic
through `rest-server` in append-only mode over the guest's tailnet-only network
boundary. Restricted SFTP remains a supported fallback when operating the
additional service is not acceptably small for the owner.

## Rationale

Append-only admission prevents the ordinary backup client from deleting old
restic snapshots through the same credential used to create new snapshots.
`rest-server` adds one bounded service inside the already dedicated guest and
does not require Artifact Memory to host a service or place network details in
canonical records. ZFS snapshots remain mandatory because append-only restic
does not protect against guest administration mistakes, repository corruption,
or storage-level destructive access.

Restricted SFTP is operationally simpler and remains viable with a dedicated
non-root account plus ZFS snapshots, but it does not provide the same
application-level append-only boundary. Both profiles require client-side
restic encryption, authenticated transport, no public inbound service, and
externally held recovery material.

## Boundaries

Tailscale runs only in the guest, never on the Proxmox host. A console or local
recovery path must remain available so restore does not depend exclusively on
the tailnet. The endpoint proves off-machine custody only; it is not
geographically off-site. Future provider, geography, and jurisdiction diversity
must remain selectable without changing canonical record or receipt identity.

No remote write is authorized by this decision. The owner must first confirm
the VM address, account, repository storage, service, and ZFS snapshot schedule.
Passphrases and private recovery material are never requested or recorded.
