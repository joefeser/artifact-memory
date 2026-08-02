# Decision 0012: version the aggregate synthetic conformance fixture

Status: accepted
Date: 2026-08-02

Issue: #12.

Artifact Memory uses a versioned aggregate manifest and runner-neutral
expected-results document to select representative conformance behavior across
the repository. The aggregate references existing synthetic vectors by
repository-relative path and exact SHA-256 file digest; it does not duplicate
their product contracts or make those paths durable protocol identity.

V1 requires valid, invalid, equivalent, collision, and unsupported classes.
Expected outcomes, diagnostic codes, and JSON Pointer equality assertions are
data, not Python test-framework behavior. Unknown schemas and operations,
missing class/result coverage, unsafe paths, and changed input bytes fail
closed.

This layout gives independent implementations one stable inventory and result
format while allowing contract-specific vector sets to evolve under their own
version identifiers. The checked receipt proves only newly authored synthetic
cases. It establishes neither authenticity nor any access, disclosure,
mutation, execution, declassification, or approval authority.
