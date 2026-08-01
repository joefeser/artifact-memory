# v0 scan policy and completeness receipts

Status: normative for `artifact-memory/scan-policy/v2` and
`artifact-memory/scan-receipt/v2`

## Policy identity and scope

A scan policy names a logical storage endpoint and a normalized relative root.
It never records the machine path used to resolve that scope. The policy digest
is SHA-256 over the canonical policy object after removing only `policy_id` and
`policy_digest`; `policy_id` is the corresponding
`scan-policy://sha-256/<hex>` URI.

The empty string denotes the endpoint root. Every non-empty root and exclusion
prefix is a normalized relative POSIX path: no absolute path, backslash,
empty segment, `.` segment, or `..` segment is admitted.

The digest therefore binds endpoint identity, relative root, comparison
profile, link behavior, declared exclusion prefixes, and extensions. Unknown
required extensions fail closed. V0 supports only the case-sensitive Unicode
code-point comparison profile and does not follow links.

Attempt bounds such as maximum entries, maximum bytes, and whether caller
cancellation is enabled are receipt facts, not policy identity. This keeps
manifests from the same semantic scope comparable while ensuring each receipt
states the bounds under which its observation was attempted.

## Exclusions and reads

Exclusion prefixes are unique, sorted, normalized relative paths. A prefix
matches itself and descendants. The scanner applies a declared exclusion after
directory enumeration reveals an entry name but before reading entry metadata,
following a link, opening a directory, or reading content. Each exclusion is
recorded with its relative path and matching rule. Declared exclusions are
outside the effective scope and do not by themselves make a scan partial.

## Outcomes and evidence

- `complete` means every non-excluded in-scope entry was accounted for and no
  warning or failure made the observation incomplete.
- `partial` means the root was observed but at least one in-scope fact remains
  unaccounted for or ambiguous.
- `failed` means the declared root could not be admitted.
- `cancelled` means caller cancellation ended the attempt before completion.

Case-fold collisions and resource bounds are warnings that prevent a complete
claim. Unreadable, unstable, unsupported, and resolver-unavailable observations
are failures. An unstable file contributes no digest. Warnings, failures, and
declared exclusions remain separately readable; `diagnostics` is retained as
a compatibility projection.

Each receipt records whole-second timezone-aware start and end times,
an independently generated UUID v4 attempt ID, implementation name and version,
logical scope, effective attempt bounds, policy ID and digest, manifest ID,
normalized tree digest, counts, and the authority boundary. The attempt ID keeps
otherwise identical attempts distinct. The receipt identifier is SHA-256 over
the canonical receipt body.
Receipt validation rejects reversed times, mismatched counts, identity
tampering, and supplied policy or manifest mismatches.

Filesystem completeness is not TraceMap analysis completeness. A scan receipt
establishes neither authenticity nor execution, disclosure, mutation, trust,
or authorization.

## Conformance evidence

`fixtures/synthetic/scan/v2/` contains newly authored synthetic observer-event
vectors for a complete file, a pre-read exclusion, an inaccessible entry, a
changing file, byte-budget exhaustion, an unavailable root, and cancellation.
Replay the checked machine and human receipts with:

```sh
python3 scripts/run_scan_conformance.py --check
```

These synthetic events prove contract behavior. They are not evidence about a
production filesystem or a particular operating system.
