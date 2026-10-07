# Security

## Reporting a vulnerability

Please **do not open a public issue** for security problems. Use GitHub's
[private vulnerability reporting](../../security/advisories/new) for this repository
instead. Include what you found, how to reproduce it and which version you used. You will
get an answer as soon as possible; fixes are released as a new version with a note in the
release text.

## How MySafe protects your data

| | |
|---|---|
| Vault file | The whole SQLite database is encrypted with **AES-256-GCM** under a random 256-bit data key. The file header is authenticated, so any change to the file is detected. |
| Master password & recovery key | Each is stretched with **Argon2id** (64 MiB, 3 passes, 4 lanes) into an X25519 key; the data key is sealed to it (X25519 + HKDF-SHA256 + AES-GCM). |
| Key rotation | Changing the master password or the recovery key switches to a **new data key**. Old keys are kept only inside the encrypted database (to open and update older copies); backups next to the vault are re-encrypted at once. |
| Sync | Another copy's password/recovery key is adopted only if you unlock that copy with *its* password during the sync, its change is newer, not dated in the future and not weaker. |
| Hostile files | Every value in a file header is checked before use (bounded Argon2 settings, sizes), so a damaged or crafted file shows an error instead of freezing or crashing MySafe. |
| On disk | The decrypted database exists only in memory. Saves are atomic; files are created readable only by you on Linux (0600 / 0700). |
| Clipboard | Copied secrets are cleared after a few seconds and on lock/quit, and marked so Windows clipboard history / cloud clipboard and KDE's clipboard manager don't keep them. |
| Unlock attempts | After 5 wrong attempts the lock screen makes you wait (5–30 s). This only slows down someone at the keyboard — the real protection against guessing a stolen file is Argon2id. |
| Build | Release programs are built by GitHub Actions from the tagged source and checked with `--self-check`; a SHA-256 checksum is published next to each download. |

The full design is described in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## What MySafe does not protect against

- **Malware on the computer** (keyloggers, screen grabbers, memory readers) while MySafe is
  unlocked — no password manager can.
- **A weak master password.** Argon2id makes guessing slow, not impossible. Use a long one.
- **Losing both the master password and the recovery key.** There is no back door; nobody
  can recover the data.
- **Memory wiping is best effort.** Python and Qt may keep copies of secrets in memory
  until the program ends.
- **An old USB copy** still opens with the password it had until it is synced once after a
  password change.

MySafe has not had an independent security audit yet.
