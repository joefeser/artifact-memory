# Release Attestation Verification Receipt

- Outcome: pass
- Release: `artifact-memory/v0.1.0`
- Tag: `v0.1.0`
- Source commit: `0123456789abcdef0123456789abcdef01234567`
- Verified subjects: 6

## Subject Set

- `artifact-memory-0.1.0-preview.tar` — `sha256:7c97d452bb488dfa6d192552f7148d57fcaa9c7bcb9988a95eae1fa17eb5d297` (44 bytes)
- `release-candidate-preparation-receipt.json` — `sha256:975ae63cc02328b8f8614a8804257531f1e14529a6066e87288441b3a41e41f5` (30 bytes)
- `release-candidate-preparation-receipt.md` — `sha256:bd4b1c1041f75671cd7a4e65620cccba522f07d72365a7c4907442839ab2fa4c` (24 bytes)
- `release-candidate-verification-receipt.json` — `sha256:3f87caf8f94dd83028383b483a1df146b235cba72d19d2e7bb1230c6b5a99393` (2142 bytes)
- `release-manifest.json` — `sha256:acccbee61e95d1f8db9997d972462a188c0ea3e693b2be4a0d0c6cf00da05606` (3090 bytes)
- `v0-preview-SHA256SUMS` — `sha256:ff3a4b218f7d335cffa3a200c27135d45d8686a4d844448ad7f333fa77bea0b7` (32 bytes)

## Limitations

- keyless attestation records workflow identity and subject digests; it grants no signing, publication, deployment, execution, or other authority.
- This receipt records deterministic replay and exact subject digests; it does not by itself prove publication or that a keyless attestation was issued.
