-- 0004: data keys this vault used before (the whole database is encrypted, so these are too).
-- Needed to open older copies of the vault (a USB stick not synced since the password
-- changed, older backups) so they can be brought up to date and re-encrypted.

CREATE TABLE key_history (
    data_key    BLOB PRIMARY KEY,
    retired_at  INTEGER NOT NULL
);
