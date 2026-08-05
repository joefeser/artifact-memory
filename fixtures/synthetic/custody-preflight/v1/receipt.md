# Custody write preflight receipt

- Outcome: `not-authorized`
- Receipt: `custody-write-preflight-receipt://52931e471b04faf1a9d951d0e25d4c5272da84b1d15bf900159e5e01618d29fe`
- Endpoint: `endpoint://joe-home-proxmox-vault-1`
- Adapter: `artifact-memory/restic-rest-server-config/v1`
- Transport: `restic-rest-server`
- Bound states: 12

This synthetic preflight proves only that the checked endpoint and adapter states agree. No network connection or remote write was attempted, and explicit owner authorization remains required before any remote write.
