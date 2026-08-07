# Independent exchange synthetic fixture

This newly authored fixture proves the bounded issue #23 seam between the v2
reference sender and a materially separate stdlib-only receiver. The receiver
does not import Artifact Memory validation, exchange, canonicalization, or
receipt helpers. Both receiver implementations emit the same schema-valid
admission receipt for an unknown optional extension, an unsupported required
extension, that required extension after support is explicitly declared,
identical duplicate manifest declarations, a v1 record with an opaque legacy
extension, and complete or malformed required-looking v1 declarations at the
v2 admission boundary.

Artifact retrieval is not attempted. The fixture carries no execution,
disclosure, routing, spending, credential, deployment, merge, mutation,
authenticity, or trust authority.
