PRAGMA foreign_keys = ON;
PRAGMA user_version = 1;

CREATE TABLE projection_metadata (
    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
    projection_schema_id TEXT NOT NULL,
    canonical_json_profile TEXT NOT NULL,
    source_record_set_digest TEXT NOT NULL,
    record_count INTEGER NOT NULL CHECK (record_count >= 0)
);

CREATE TABLE records (
    record_id TEXT PRIMARY KEY,
    record_type TEXT NOT NULL,
    lifecycle TEXT NOT NULL,
    sensitivity TEXT,
    record_json TEXT NOT NULL,
    source_record_set_digest TEXT NOT NULL
);
CREATE INDEX records_type_idx ON records(record_type, record_id);
CREATE INDEX records_lifecycle_idx ON records(lifecycle, record_id);

CREATE TABLE provenance (
    record_id TEXT NOT NULL REFERENCES records(record_id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    provenance_kind TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    PRIMARY KEY (record_id, ordinal)
);
CREATE INDEX provenance_source_idx ON provenance(source_ref, record_id);

CREATE TABLE relationships (
    source_record_id TEXT NOT NULL REFERENCES records(record_id) ON DELETE CASCADE,
    relationship_type TEXT NOT NULL,
    target_ref TEXT NOT NULL,
    PRIMARY KEY (source_record_id, relationship_type, target_ref)
);
CREATE INDEX relationships_target_idx ON relationships(target_ref, source_record_id);

CREATE VIRTUAL TABLE records_fts USING fts5(
    record_id UNINDEXED,
    summary,
    labels
);
