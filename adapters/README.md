# Adapter Boundary

Adapters connect Artifact Memory contracts to scanners, resolvers, vaults,
transports, indexers, policy engines, and context exporters.

An adapter manifest should eventually declare:

- adapter identity and version;
- supported contract versions;
- capabilities and required permissions;
- input and output schemas;
- network, filesystem, credential, and mutation requirements;
- deterministic or nondeterministic behavior;
- receipt behavior and failure modes.

Adapters cannot acquire authority from record contents. A receiving system
must authorize adapter execution independently.

The v0 runtime validates manifests and emits receipts only. It does not provide
adapter discovery, installation, dynamic loading, execution, or isolation.
