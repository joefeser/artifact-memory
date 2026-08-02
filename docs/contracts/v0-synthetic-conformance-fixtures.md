# v0 synthetic conformance fixture layout

Status: normative for `artifact-memory/conformance-fixture-*/v1`

The aggregate conformance fixture is a language-neutral inventory over
existing synthetic vectors. It does not replace the normative contract-specific
vectors or convert provider contracts into Artifact Memory core schemas.

## Manifest and input binding

`conformance-fixture-manifest/v1` identifies one synthetic fixture set and its
cases. Each case declares exactly one of five behavior classes—`valid`,
`invalid`, `equivalent`, `collision`, or `unsupported`—a versioned operation,
exactly one repository-relative synthetic input reference, and an expected
result reference. V1 operations intentionally use one input; an operation that
composes multiple inputs requires a later fixture contract version.

Every input reference is bound to the SHA-256 digest of the exact file bytes.
Absolute paths, parent traversal, symlink traversal, unavailable files, and
digest mismatches fail closed. Paths are transport references inside the
public fixture package, not durable artifact, content, endpoint, or location
identity.

The manifest carries an affirmative provenance declaration. V1 admits only
newly authored synthetic material and explicitly states that the fixture is not
production-derived. Redaction alone does not make source material synthetic.

## Runner-neutral expected results

`conformance-expected-results/v1` binds each case to an outcome, ordered
diagnostic codes, and zero or more equality assertions addressed with JSON
Pointers. It contains no Python class names, exception text, filesystem mount
roots, provider-specific schema, or test-framework convention.

Pointer tokens use RFC 6901 `~0` and `~1` escapes. Array indexes are ASCII `0`
or a nonzero ASCII digit followed by digits; leading-zero and non-ASCII indexes
fail closed. Selectors are required only for `declared-outcome-v0`, which
selects one declaration from a larger vector document. Other v1 operations
consume the whole digest-bound input and reject selectors.

V1 operations are deliberately bounded:

- `exact-content-digest-v0` reproduces exact byte, leaf, and tree digests;
- `schema-validation-v0` reports accepted or typed rejected schema behavior;
- `logical-location-equivalence-v0` exercises one logical location through
  synthetic macOS, Windows, and Linux layout adapters; and
- `declared-outcome-v0` preserves explicit collision and unsupported results.

An unknown manifest, expected-results, operation, or schema identifier fails
closed. Case IDs, result IDs, class coverage, result coverage, input digests,
outcomes, diagnostics, and assertions must all match before the aggregate
receipt can be complete.

## Claims and limits

The aggregate receipt is a reproducible proof for the checked representative
cases. Synthetic platform adapters do not prove behavior on physical devices
or every filesystem. Integrity of fixture bytes is not authenticity, trust,
custody, access, disclosure, declassification, mutation, execution, spending,
deployment, or approval authority.

The Python package contains the schemas and runtime, not the root-level public
fixture corpus. Callers outside a source checkout must ship the fixture bundle
and pass a `repository_root` containing `fixtures/synthetic/` to the API. The
aggregate fixture CLI infers that root from the enclosing `--fixture` bundle
layout. Unavailable fixture data fails with an actionable typed diagnostic.
