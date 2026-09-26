# Synthetic coordination repository identity fixture

This public-safe AM-8 fixture contains two wholly synthetic repository identity
manifests with the same display name and distinct project UUIDs. The checked
receipt proves that UUID references remain unambiguous, unknown UUIDs fail with
a typed diagnostic, and renaming a display-only `humanName` changes no
coordination-record revision digests.

Run:

```sh
python3 scripts/run_coordination_repo_identity_conformance.py --check
```

The fixture grants no execution, disclosure, authorization, or trust.
