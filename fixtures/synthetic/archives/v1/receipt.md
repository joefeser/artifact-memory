# Archive conformance receipt

- Outcome: `pass`
- Receipt: `archive-conformance-receipt://71aeb95b8ffd10577cf1522e4199f933621404e7ddcc423d9ece20c2089ac27f`
- Synthetic cases: 5

| Case | Outcome | Completeness | Diagnostics | Tree relationship |
| --- | --- | --- | --- | --- |
| `safe` | `supported` | `complete` | `none` | `yes` |
| `mixed-malicious` | `partial` | `partial` | `path-traversal, duplicate-entry, case-collision, link-entry, decompression-limit` | `no` |
| `link-only` | `unsupported` | `unavailable` | `link-entry` | `no` |
| `encrypted-only` | `unsupported` | `unavailable` | `encrypted-entry` | `no` |
| `corrupt` | `partial` | `partial` | `corrupt-entry` | `no` |

Only the safe complete case emits a container-to-extracted-tree relationship. The fixture performs bounded in-memory inspection and grants no extraction, execution, mutation, disclosure, or trust authority.
