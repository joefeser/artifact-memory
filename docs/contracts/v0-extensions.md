# v0 namespaced extensions

Only globally namespaced extension identifiers are admitted. An unknown
optional extension is preserved as opaque data and is not interpreted. An
unknown required extension fails closed. Extension values cannot redefine core
identity, digest, sensitivity, schema version, or authority fields.

V0 has no registry, discovery, marketplace, inheritance, or generalized
metadata framework. These two synthetic fixtures are the complete initial
conformance surface.
