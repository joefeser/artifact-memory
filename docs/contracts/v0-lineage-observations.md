# V0 historical lineage observations

The public [WhereAreMyFiles repository](https://github.com/joefeser/WhereAreMyFiles)
is historical evidence only. The reviewed source head is
[`3a18550fa52526e1a440a1e9264bd9f17638d89e`](https://github.com/joefeser/WhereAreMyFiles/commit/3a18550fa52526e1a440a1e9264bd9f17638d89e).
Artifact Memory does not copy its C# source, Windows-specific SQLite model,
binaries, or schema text into this Apache-2.0 repository.

## Historical mapping

| Historical entity or behavior | V0 interpretation | Boundary |
| --- | --- | --- |
| `DriveInformation` | storage-location discovery evidence | Drive letter, model, serial number, volume name, and size are observations; none is durable endpoint or artifact identity. |
| `DirectoryInformation` | historical path-hierarchy observation | Database IDs, parent IDs, and Windows paths are not canonical IDs or portable manifest paths. |
| `FileInformation` | historical file observation | Name, path, length, timestamps, and SHA-1 do not establish a current artifact, version, content object, or location. |
| `FileAttribute` and `FileAttributeInformation` | platform-specific metadata observations | Attribute names and values have no portable core meaning unless a later adapter supplies an explicit mapping and evidence. |
| SQLite tables, indexes, and local integer keys | replaceable historical query projection | The database and its identifiers are not canonical records and are not imported as Artifact Memory schemas. |
| SHA-1 grouping and planned duplicate lookup | historical comparison evidence | SHA-1 equality is never promoted to exact-content identity. |
| Recursive Windows scan | incomplete historical scan evidence | Ignored and inaccessible entries mean completeness is not established. |
| README ZIP/7z phases | unimplemented roadmap | Planned phases are not evidence of archive support. |

This mapping is conceptual and intentionally does not reproduce the historical
database definitions.

## Read-only experiment

The optional read-only observation accepts only a complete row with a non-empty
path and timestamps, a non-negative byte size, and either the exact historical
`NONE` sentinel or a 40-hex SHA-1 value. Missing or malformed evidence fails
closed with `legacy-evidence-insufficient`; an unattributed source fails with
`legacy-source-unsupported`. The experiment does not migrate bytes, create
current identity, resolve a path, or mutate the source.

A historical SHA-1 value remains labeled SHA-1 and is never converted into a
SHA-256 claim. `NONE` means only that the old application recorded no hash; it
does not mean empty content, a failed read, or a known content identity.

## Limitations

The implementation was Windows-specific, used WMI and drive-letter-based
discovery, skipped known protected folders, tolerated access failures, and did
not prove a complete filesystem inventory. Files at or above its two-billion-
byte hashing threshold were stored as `NONE`. Metadata and filesystem state may
have changed after collection. No historical observation establishes present
existence, custody, authenticity, trust, disclosure permission, or authority.

## Licensing and attribution

The inspected C# source files carry per-file MIT license headers and copyright
attribution to Joe Feser (2010). The historical repository has no root license
file recognized by GitHub, so this is a scoped per-file statement—not a blanket
license claim for bundled SQLite assemblies or other dependencies. No historical
source, binary, dependency, or schema text is redistributed here. Any future
reuse requires its own provenance and license review.

## Checked evidence

The two-row synthetic fixture covers both `NONE` and a valid SHA-1 observation
and retains a machine-readable and human-readable receipt:

```sh
python3 scripts/run_legacy_lineage_conformance.py --check
```
