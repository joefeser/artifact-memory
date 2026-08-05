# Custody write preflight receipt

- Outcome: `not-authorized`
- Receipt: `custody-write-preflight-receipt://4b6ea398981610db93ab71799eb63a3bd6c80d3016fac37f18d3680dde683ffe`
- Endpoint: `endpoint://joe-home-proxmox-vault-1`
- Adapter: `artifact-memory/restic-sftp-config/v2`
- Transport: `restic-over-sftp`
- Bound states: 9
- Authority boundary: custody preflight evidence grants no remote-write, execution, credential, or infrastructure authority

## Limitations

- no network connection or remote write was attempted
- connection details and secret material are not represented
- explicit owner authorization remains required before any remote write

This synthetic preflight proves only that the checked endpoint and adapter states agree.
