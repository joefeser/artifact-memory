# Decision 0010: separate artifact identity from immutable version lineage

Status: accepted
Date: 2026-08-01

Issue: #8.

Artifact Memory gives a meaningful thing one stable logical artifact identity
while representing each immutable revision with a separate artifact-version
identity. Exact content remains a third identity. Paths, locations, filenames,
provider references, and content digests cannot substitute for artifact or
version identity.

V0 assigns every version one of five roles: original, normalized, redacted,
derived, or released. Non-original versions must carry typed source lineage.
Versions may bind multiple exact content objects, and identical content can be
reused without collapsing semantic identities.

Correction is additive. A newer version may explicitly `supersedes` an earlier
retained version, but it cannot overwrite or erase that target. Same-artifact
lineage points backward by revision, and ambiguous multiple direct superseders
fail closed in a bounded supplied history.

Consequences: the minimal `artifact-version/v1` schema remains packaged for
compatibility. New contract work uses `artifact/v1` and `artifact-version/v2`.
Provenance and lineage remain evidence only; they establish neither
authenticity nor access, disclosure, mutation, execution, trust, or authority.
