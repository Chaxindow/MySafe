# MySafe — Architecture

MySafe is a desktop password manager (Python 3.11+, PySide6). This document describes its
layers, data flow, vault format and the security decisions behind them. The code is the
source of truth; the layer rules below are enforced by `tests/test_architecture.py`.

## 1. Layers

```
┌──────────────────────────────────────────────────────────────────────┐
│ app.py   composition root: start-up, Session (lock, password, USB,   │
│          Sync, restore), wires Vault + AppController + MainWindow    │
└───────┬──────────────────────────────────────────┬───────────────────┘
        │                                          │
┌───────▼──────────────────────────┐  ┌────────────▼─────────────────────┐
│ ui/  (PySide6)                   │  │ vault.py  Vault: file + crypto + │
│  controller.py  AppController    │  │           in-memory database     │
│  main_window, panels, dialogs    │  │ sync.py   plan_sync / apply_sync │
└───────┬──────────────────────────┘  │ paths.py, self_check.py          │
        │ (only controller → db)      └──────┬─────────────────┬─────────┘
┌───────▼───────────────────────────────────▼──┐  ┌────────────▼─────────┐
│ db/  connection.py (open, migrate,            │  │ services/            │
│      serialize), repository.py (all SQL)      │  │  crypto, vault_file, │
│      migrations/0001–0004.sql                 │  │  password_generator, │
└───────┬───────────────────────────────────────┘  │  password_strength   │
        │                                          └────────────┬─────────┘
┌───────▼──────────────────────────────────────────────────────▼─────────┐
│ models.py   Category, Entry, Field, FieldKind, DeletedItem (stdlib only)│
└─────────────────────────────────────────────────────────────────────────┘
```

Rules checked by `tests/test_architecture.py` (imports are read with `ast`, nothing is run):

- `mysafe.models` imports nothing from `mysafe`.
- `mysafe.db`, `mysafe.services` and `mysafe.models` never import `PySide6`, `mysafe.ui`
  or `mysafe.app`.
- Only modules inside `mysafe.db` import `sqlite3`.
- `mysafe.db` and `mysafe.services` do not import each other.
- `mysafe.ui` never imports `mysafe.app` or `mysafe.demo`.
- Inside `mysafe.ui`, only `mysafe.ui.controller` imports `mysafe.db`.

Other UI modules may use `models`, `services` (password generator/strength, crypto error
types), `sync` types (the Sync dialog) and `paths`. The top-level modules `vault.py`,
`sync.py` and `self_check.py` are where `db` and `services` are combined.

## 2. Data flow

- Panels and dialogs call `AppController`; it calls `Repository` and emits
  `categories_changed` / `entries_changed` / `settings_changed`, after which views reload.
  Expected errors (`RepositoryError`, `ValueError`) become an `error_occurred` signal.
- Every write in `Repository` runs in one transaction and then calls `on_change`. `Vault`
  passes `on_change=self.save`, so **every change is encrypted and written to disk at once**;
  there is no "Save" button.
- `Repository.batch()` suspends `on_change` and fires it once at the end, so a Sync, a
  settings change or a key change produces a single save.
- Settings (theme, clipboard clear time, auto-lock minutes, sync target) live in the `meta`
  table, i.e. inside the encrypted vault.

## 3. Database

The decrypted SQLite database exists **only in memory**: `open_from_bytes` loads it with
`sqlite3.deserialize`, `to_bytes` takes a snapshot with `serialize` before encryption.
An old unencrypted `mysafe.db` is imported once on first start and then overwritten and
deleted (best effort).

Migrations are numbered SQL files (`NNNN_name.sql`, 1..N without gaps), each applied in its
own transaction; `PRAGMA user_version` stores the schema version, and a database newer than
the app is refused.

| File | Change |
|---|---|
| `0001_initial.sql` | `categories`, `entries`, `fields` (cascade on entry delete), `meta` |
| `0002_rename_movies_to_streaming.sql` | default category "Movies & Series" → "Streaming" |
| `0003_deleted_items.sql` | `deleted_items` tombstones (entry/category, title, time) for Sync |
| `0004_key_history.sql` | `key_history`: data keys used before, with retirement time |

## 4. Vault file and encryption (`services/crypto.py`, format version 2)

```
MAGIC "MYSAFE\0\1" | header length (u32 BE) | header JSON | nonce (12) | AES-256-GCM body
```

- The body (the database image) is encrypted with AES-256-GCM under a random 256-bit
  **data key**; `MAGIC + header` is the associated data, so any header change breaks
  decryption. Header values are bounds- and type-checked before use (max 64 KiB header).
- The header holds `vault_id`, `kdf_params`, `keys_updated_at` and two **key slots**:
  `password` and `recovery`. Each slot is a public-key envelope: the secret is stretched
  with **Argon2id** (default m = 64 MiB, t = 3, p = 4) into an X25519 private key; only the
  public key and salt are stored. The data key is sealed with a fresh ephemeral X25519 key,
  HKDF-SHA256 and AES-GCM. KDF values read from a file must lie between 8 MiB/1/1 and
  1 GiB/20/16, so a hostile file cannot freeze the app.
- **Why public-key slots:** sealing only needs the public key. On every password or
  recovery-key change MySafe generates a **new data key** and seals it to both slots
  without knowing the other secret. An old copy opened with an old password therefore only
  yields an old data key.
- Old data keys are stored in the encrypted `key_history` table, so older copies (an
  unsynced USB stick, backups) can still be opened and re-encrypted. After a key change,
  backups (`.bak`, `.before-sync`, `.before-restore`) are re-encrypted with the new keys.
- Format 1 (symmetric slots, no rotation) is still opened and upgraded on unlock; since the
  old recovery key cannot be carried over, a **new recovery key** is shown once.
- Passwords are NFC-normalised before use (format 1 fallback: the raw bytes).
- Recovery key: 160 random bits, base32, shown as 8 groups of 4 characters. Input is
  accepted with/without dashes, any case; `0/1/8` are read as `O/I/B`.

## 5. Saving (`services/vault_file.py`, `Vault.save`)

- Atomic write: data → `<name>.tmp` → flush + `fsync` → `os.replace`, then the folder is
  `fsync`ed (not on Windows). The previous file is kept as `<name>.bak` (written the same
  way). Leftover `.tmp` files are removed when a vault is opened.
- Files are created with mode `0600`, the folder with `0700` on POSIX (ignored where the
  file system has no permissions, e.g. FAT USB sticks).
- Digest guard: `Vault` remembers the SHA-256 of the file it last read/wrote. If the file
  changed since (another window, a Sync from the other side), `save` raises
  `VaultChangedElsewhereError` instead of overwriting it.

## 6. Data locations and portable mode (`paths.py`)

Data folder, in order: `MYSAFE_DATA_DIR` (dev/tests) → `MySafe-data` next to the frozen
executable (portable mode) → `%APPDATA%\MySafe` (Windows) / `~/.local/share/MySafe` (Linux).
`MYSAFE_PORTABLE=1` forces portable behaviour for testing. The vault file is `vault.mysafe`.

"Create USB copy" writes an encrypted copy to `<folder>/MySafe-data/vault.mysafe`, stores
the original's path as the copy's sync target, and — in the packaged app — copies the
program next to `MySafe-data`, so the stick runs on another computer. A portable instance
syncs back to the computer vault by default.

## 7. Sync (`sync.py`, `Session.sync` in `app.py`)

`plan_sync` only reads both repositories; the user reviews the plan; `apply_sync` writes
both sides inside `batch()` (one save each). Both vault files are snapshotted to
`.before-sync` first.

- **New entries** (on one side, not deleted on the other) are copied automatically.
- **Conflicts** (same id, different content): the user chooses; the newer is preselected.
- **Deletions** (tombstone on one side, entry still on the other): "delete on the other side
  too" is preselected; otherwise the entry is restored where it was deleted.
- **Categories**: new ones are copied, same-name categories are merged, renames: newest wins.
- Remaining **tombstones** and **key history** are merged in both directions.

Opening the other copy: first with this vault's current and old data keys. If that fails
but the `vault_id` matches (`NeedsPasswordError`), the copy's password was changed there and
the user is asked for it.

Keys afterwards (`keys_source`): the copy's keys are adopted only if it was unlocked with
its own password in this sync, its `keys_updated_at` is newer, not more than 24 h in the
future, and its KDF settings are not weaker. Otherwise this vault's keys are written to the
copy. A tampered copy can therefore never change this vault's password. Backups on both
sides are then re-encrypted.

## 8. Restore from backup

`Vault.backups()` lists the backups this vault can open (Before sync, Before restore,
Previous save) with date and entry count. `Vault.restore()` first saves the current state
as `.before-restore` (so a restore can be undone; undoing swaps the two), loads the backup,
keeps the current keys and key history, and saves. The window is rebuilt afterwards.

## 9. Lock, clipboard, unlock attempts

- **Lock** (Ctrl+L) and **auto-lock** (idle timer, off by default) close the window, the
  in-memory database and wipe the data key, then show the lock screen. Auto-lock first
  closes any open dialog (unsaved edits are dropped).
- **Clipboard**: copied secrets are cleared after a delay (default 20 s) if still on the
  clipboard, and cleared on lock and quit. They are marked to be excluded from Windows
  clipboard history and cloud clipboard (and as a password for KDE's clipboard manager).
- **Wrong attempts**: after 5 free attempts the unlock dialog waits 5 s, 10 s, … up to 30 s.
  This is only a UI nuisance; the real protection against offline guessing is Argon2id.

## 10. Packaging and CI

- `tools/build.py` builds a one-file PyInstaller program (`dist/MySafe.exe` / `dist/MySafe`),
  runs it with `--self-check <report>` (migrations, database, create/unlock/recovery of a
  throw-away vault, icons; no window, user data untouched) and writes a `.sha256` file.
- `.github/workflows/ci.yml`: tests on Windows and Ubuntu with Python 3.11 and 3.13
  (pytest, ruff check, ruff format --check, mypy); builds on both systems; a `v*` tag
  publishes the builds as a GitHub release.

## 11. Threat model

Protected against:
- A stolen vault file, laptop disk or USB stick (AES-256-GCM, Argon2id-stretched secrets).
- Other local users (private file and folder modes on POSIX; Windows user-profile ACLs).
- Old passwords after a change: the data key rotates and local backups are re-encrypted;
  an unsynced old copy only reveals the data as it was then.
- Tampered or damaged files, including sync copies: authenticated header and body, checked
  header values, and key adoption rules that never accept a forged or weaker key change.

Not protected against:
- Malware, keyloggers or screen capture on the machine while the vault is unlocked.
- A weak master password (Argon2id slows guessing but cannot make a weak password strong).
- Losing both the master password and the recovery key: the data cannot be recovered.
- Secrets lingering in memory: wiping keys is best effort in Python.
