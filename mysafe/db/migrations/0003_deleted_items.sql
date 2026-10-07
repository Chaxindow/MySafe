-- 0003: remember deletions so that Sync can carry them to the other vault

CREATE TABLE deleted_items (
    id          TEXT PRIMARY KEY,                 -- id of the deleted entry/category
    kind        TEXT NOT NULL CHECK (kind IN ('entry', 'category')),
    title       TEXT NOT NULL,                    -- shown in the Sync screen
    deleted_at  INTEGER NOT NULL
);
