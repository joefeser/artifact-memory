# Synthetic coordination sync vectors

These wholly synthetic vectors pin the v0 pair-set digest, typed admission
outcomes, rejected outcome/code contradictions, unique TaskPacket genesis,
record-bound AccessLabel egress, and the pagination boundary. They contain no
vault data, credentials, private topology, customer material, or raw
conversations.

Run the bounded acceptance proof with:

```sh
python3 scripts/run_coordination_sync_conformance.py --check
```

The local-directory hub used by the proof is a provider-free protocol adapter,
not a claim of WITS HTTP interoperability or issuer authenticity.
