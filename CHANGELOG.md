# Changelog

## 0.1.0 — 2026-10-07

First public release.

- Categories and entries with custom fields (email, username, password, recovery code,
  security question, URL, note, text), search, favorites, copy with auto-clear,
  password generator, naming guide, light/dark theme.
- Encrypted vault: AES-256-GCM, Argon2id, master password + recovery key, key rotation on
  every password / recovery-key change, two-step recovery, clear wrong-attempt feedback.
- Lock (Ctrl+L) and optional auto-lock.
- USB copy (vault + program on the stick) and two-way Sync with side-by-side conflicts,
  deletion markers and backups before every sync.
- Restore from backup (undoable).
- Single-file programs for Windows and Linux, built and self-checked by GitHub Actions.
