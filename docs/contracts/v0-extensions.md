# v0 namespaced extensions

Only globally namespaced extension identifiers are admitted. An unknown
optional extension is preserved as opaque data and is not interpreted. An
unknown required extension fails closed. Extension values cannot redefine core
identity, digest, sensitivity, schema version, or authority fields.

An extension identifier is an HTTPS namespace controlled independently of the
core contract. Each declaration carries an explicit `version`, `required`
flag, and object-valued `value`. The identifier names the extension schema;
the version selects that schema's declared revision. A bundle may carry an
`extensions_digest`, which must equal the SHA-256 digest of the canonical
extension map when present.

Required-extension support is declared for the exact `(identifier, version)`
pair. Supporting another version under the same identifier does not satisfy a
required declaration.

Extension keys remain nested under `extensions`, so identically named fields
inside an opaque value never replace top-level core fields. Applying a bundle
also fails closed if it would overwrite a different declaration already stored
under the same extension identifier.

The legacy `knowledge-record/v1` contract predates the structured bundle and
continues to preserve arbitrary extension values opaquely. The independent
reader interprets required/optional semantics only when a value is a complete,
valid structured declaration; all other v1 values remain uninterpreted. Reader
support declarations are validated as exact `(identifier, version)` pairs.
The reference runtime derives identifier and version validity from the public
extension-bundle schema. The materially separate stdlib reader reimplements
that grammar locally so conformance does not merely exercise shared code.

V0 has no registry, discovery, marketplace, inheritance, or generalized
metadata framework. These two synthetic fixtures are the complete initial
conformance surface.
