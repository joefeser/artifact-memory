# Synthetic Fixtures

Only synthetic fixtures belong here.

Fixtures must not be copied from private vaults, customers, browser sessions,
production logs, raw task transcripts, or proprietary documents—even after
light redaction.

The versioned aggregate inventory is under `conformance/v1/`. It binds one
representative valid, invalid, equivalent, collision, and unsupported case to
exact input digests and runner-neutral expected results. Contract-specific
fixtures remain authoritative for their broader behavior.

The wider fixture set covers or is expected to cover:

- equivalent logical trees under Windows, macOS, and Linux paths;
- case and Unicode collisions;
- empty files and directories;
- large and sparse files;
- symbolic and hard links;
- unreadable and excluded entries;
- archives and extracted-tree relationships;
- unknown optional and required extensions;
- replayed and contradictory exchange receipts.
