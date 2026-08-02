# V0 artifacts, immutable versions, and lineage

Status: normative for `artifact-memory/artifact/v1` and
`artifact-memory/artifact-version/v2`

## Identity separation

An artifact is a stable logical identity for a meaningful thing. Its
`artifact://<namespace>/<name>` identifier is owner-assigned and is not derived
from a filename, path, location, content digest, provider URL, or version.

An artifact version is one immutable revision of that artifact. Its
`artifact-version://<namespace>/<name>/<revision>` identifier must bind the same
namespace and name as `artifact_id`, and the final positive integer must equal
`revision`. Revision numbers order the supplied history; they do not claim that
the supplied history is globally complete.

A content object identifies exact bytes. An artifact version binds one or more
unique, sorted `content://sha-256/<hex>` references. Reusing the same content
object across artifacts or versions does not merge their semantic identities.
Neither artifact nor version records contain location observations or resolver
paths.

## Roles and lineage

The v0 roles are `original`, `normalized`, `redacted`, `derived`, and
`released`. Every non-original role names its source using the corresponding
typed relationship:

| Role | Required relationship |
| --- | --- |
| `normalized` | `normalized-from` |
| `redacted` | `redacted-from` |
| `derived` | `derived-from` |
| `released` | `released-from` |

`related-to` records a non-lineage association. Lineage within the same
artifact must point to an earlier retained revision. External lineage may point
to another artifact version, but validation of that external history requires a
separate bounded input.

Provenance records an asserted author, observation, import, derivation,
normalization, redaction, or release source. It does not establish authenticity,
issuer control, trust, custody, permission to disclose, or authority.

## Supersession without replacement

`supersedes` is an explicit relationship on the newer version. The target must
be an earlier retained version of the same artifact. A bounded history rejects
forward supersession, missing same-artifact targets, and multiple direct
successors that claim to supersede the same retained version.

Supersession never deletes, mutates, or silently replaces the target version or
its content bindings. Lifecycle metadata cannot be used as permission to
rewrite immutable version history; retention or deletion is governed by the
separate lifecycle contract.

## Extensions and authority

Unknown optional namespaced extensions are preserved and identity-relevant
within their containing canonical record. Unknown required extensions fail
closed. Extensions cannot redefine artifact, version, revision, role, content,
lineage, provenance, or authority semantics.

Artifact identity and lineage grant no content access, execution, disclosure,
mutation, authenticity, trust, declassification, routing, or authorization.

## Conformance evidence

`fixtures/synthetic/artifact-lineage/v1/` retains six newly authored synthetic
versions covering every v0 role, two multi-content versions, typed derivation,
and an explicit supersession whose target remains present. Replay the checked
machine and human receipts with:

```sh
python3 scripts/run_artifact_lineage_conformance.py --check
```

The fixture proves contract behavior for the bounded supplied history. It does
not prove that a real artifact, issuer, source, or external version exists.
