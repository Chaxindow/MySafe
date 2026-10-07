-- 0001: initial schema

CREATE TABLE categories (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE COLLATE NOCASE,
    icon        TEXT,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    created_at  INTEGER NOT NULL,
    updated_at  INTEGER NOT NULL
);

CREATE TABLE entries (
    id           TEXT PRIMARY KEY,
    category_id  TEXT NOT NULL REFERENCES categories(id) ON DELETE RESTRICT,
    title        TEXT NOT NULL,
    url          TEXT,
    notes        TEXT,
    favorite     INTEGER NOT NULL DEFAULT 0,
    created_at   INTEGER NOT NULL,
    updated_at   INTEGER NOT NULL
);

CREATE INDEX idx_entries_category ON entries(category_id);

CREATE TABLE fields (
    id          TEXT PRIMARY KEY,
    entry_id    TEXT NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
    label       TEXT NOT NULL,
    value       TEXT NOT NULL,
    kind        TEXT NOT NULL,
    is_secret   INTEGER NOT NULL DEFAULT 0,
    sort_order  INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX idx_fields_entry ON fields(entry_id);

CREATE TABLE meta (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);
