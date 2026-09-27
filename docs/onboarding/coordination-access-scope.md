# Export scoped coordination context

AM-7 exports informational coordination context only from the latest verified
authorized projection created by coordination sync. It does not scan every
canonical record in the vault or accept a caller assertion that a record is
authorized.

First complete the provider-free sync flow described in
[local coordination sync proof](local-coordination-sync-proof.md). Then export
the current authorized projection:

```sh
artifact-memory coordination-context \
  --vault /path/to/private-coordination-vault \
  --json
```

The command verifies the successful-sync marker, authenticated receipt,
scope generation, AccessLabel reference, authorized pair-set count and digest,
and every exact `(record_id, revision_digest)` pair before returning records.
If that policy view is missing, stale, malformed, or inconsistent with local
bytes, export fails closed.

The strict `artifact-memory/coordination-context-pack/v0` result contains:

- only the records named by the verified authorized projection;
- the exact sync-receipt identity and scope generation;
- the authorized pair-set count and digest;
- a count of excluded records, without their identities; and
- an explicit informational-only authority boundary.

The pack never contains a full AccessLabel body. Project names, UUIDs, record
identities, and content for excluded records must not appear. Narrowing a label
advances the scope generation and replaces the generated membership/projection;
formerly visible records stop appearing in later exports. Their canonical
revisions remain local history, so suppression is not deletion or global
erasure.

AccessLabels reject duplicate project UUIDs and overlap between grants and
denials before use. Sync and context validation fail typed if a malformed label
nevertheless reaches evaluation. The output grants no execution, mutation,
routing, disclosure, credential, spending, deployment, approval, or merge
authority.

Run the synthetic public-safe proof with:

```sh
python3 scripts/run_coordination_access_scope_conformance.py --check
```

The receipt proves broad-to-narrow replacement, count-only exclusions,
canonical-history retention, absence of denied identities and full label
bodies, and the required fail-closed cases. It uses only synthetic UUIDs,
records, repositories, and temporary directories.
