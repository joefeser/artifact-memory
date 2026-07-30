# Adapter Boundary

Adapters connect Artifact Memory contracts to filesystems, vaults, transports,
indexes, policy engines, and agent context systems.

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

