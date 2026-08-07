# Synthetic WITS adapter fixture

This fixture carries an independently defined, opaque WITS projection
reference. It does not copy WITS BSL implementation code or product-owned
schema text. Artifact Memory retains source record revisions and the opaque
projection reference; WITS owns the meaning/readiness interpretation.

The conformance test ends at the projection and admission receipt. It creates
no HACP Task Packet, Route Task, destination, Codex continuation payload,
authority grant, or execution request.

The completed #41 fixture is documented in `conformance-README.md`. It extends
this minimum response through bounded context, generated-index rebuild,
encrypted backup, and isolated restore while preserving the same authority stop.
