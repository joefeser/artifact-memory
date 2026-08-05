# Custody write preflight receipt

- Outcome: `not-authorized`
- Receipt: `custody-write-preflight-receipt://7b659b2afa0db6c539e45f0383d23b7673eeacdc8da5a2f44487af6715bbceea`
- Endpoint: `endpoint://joe-home-proxmox-vault-1`
- Adapter: `artifact-memory/restic-sftp-config/v1`
- Transport: `restic-over-sftp`
- Bound states: 7
- Authority boundary: custody preflight evidence grants no remote-write, execution, credential, or infrastructure authority

## Limitations

- no network connection or remote write was attempted
- connection details and secret material are not represented
- explicit owner authorization remains required before any remote write

This synthetic preflight proves only that the checked endpoint and adapter states agree.
