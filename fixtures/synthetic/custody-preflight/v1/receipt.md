# Custody write preflight receipt

- Outcome: `not-authorized`
- Receipt: `custody-write-preflight-receipt://0ce7073f59984839c77f6d79f84071832b660834bc5830982470a71bb03dcf07`
- Endpoint: `endpoint://joe-home-proxmox-vault-1`
- Adapter: `artifact-memory/restic-rest-server-config/v1`
- Transport: `restic-rest-server`
- Bound states: 12
- Authority boundary: custody preflight evidence grants no remote-write, execution, credential, or infrastructure authority

## Limitations

- no network connection or remote write was attempted
- connection details and secret material are not represented
- explicit owner authorization remains required before any remote write

This synthetic preflight proves only that the checked endpoint and adapter states agree.
