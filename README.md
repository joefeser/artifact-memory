# Artifact Memory

Artifact Memory is a filesystem-first, contract-first system for identifying,
describing, locating, exchanging, and verifying knowledge and artifacts across
people, agents, machines, and storage providers.

The project begins with a simple separation:

> Records preserve meaning. Vaults hold bytes. Backups protect bytes.
> Generated indexes make records discoverable.

Artifact Memory does not assume that a filename is identity, a path is stable,
a database is canonical, or receiving knowledge grants authority to act.

## Project status

Artifact Memory is in private design incubation. The repository is being built
as public-safe open source from its first commit. Real product records,
customer material, credentials, resolver configuration, and artifact bytes
belong in private vaults and must never be committed here.

The first useful release must prove:

1. Portable, versioned JSON records.
2. Deterministic content and tree manifests.
3. Logical artifact references across different mount layouts.
4. Generated NDJSON and SQLite views that can be deleted and rebuilt.
5. Bounded knowledge exchange with explicit admission receipts.
6. Encrypted backup and clean restoration of a private dogfood vault.

## Core model

```text
Knowledge record
  What does this mean?

Artifact and version
  Which meaningful thing and immutable revision?

Content object
  Which exact bytes?

Location observation
  Where and when were those bytes observed?

Storage resolver
  How does this machine locate a logical endpoint?

Manifest and receipt
  What was scanned, transferred, admitted, or verified?
```

Canonical data is portable text validated by versioned schemas. SQLite,
NDJSON, HTML, search catalogs, and agent context packs are generated views.

## Repository boundary

This repository may contain:

- specifications and architecture decisions;
- JSON Schemas;
- reference implementations and adapter SDKs;
- synthetic fixtures;
- conformance tests;
- public-safe examples and documentation.

This repository must not contain:

- real vault records or artifact bytes;
- customer data;
- private commercial or product strategy;
- credentials, cookies, tokens, keys, or browser sessions;
- physical resolver paths or storage credentials;
- raw AI conversations or private attachments.

See [Security](SECURITY.md) and the
[repository operating rules](AGENTS.md) before contributing.

## Design

- [Foundation and rewrite concept](docs/architecture/foundation.md)
- [Initial roadmap](docs/roadmap/initial-roadmap.md)
- [Decision log](docs/decisions/README.md)
- [Extension and adapter boundary](adapters/README.md)
- [Schema work area](schemas/README.md)
- [Synthetic fixture policy](fixtures/synthetic/README.md)

## Lineage

Artifact Memory is a clean rewrite informed by
[`WhereAreMyFiles`](https://github.com/joefeser/WhereAreMyFiles), a 2010
project that indexed files, hashes, metadata, directory structure, and
removable-drive identity in SQLite. The rewrite preserves its central insight:
identity must survive changing paths and storage devices.

## License

Apache License 2.0. See [LICENSE](LICENSE).

