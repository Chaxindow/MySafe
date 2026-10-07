from __future__ import annotations

import json
import os
import struct
import unicodedata
from collections.abc import Callable
from typing import Any

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from mysafe.services import crypto
from mysafe.services.crypto import (
    CorruptVaultError,
    KdfParams,
    UnsupportedVaultError,
    WrongPasswordError,
)

FAST = KdfParams(memory_kib=8 * 1024, iterations=1, lanes=1)  # keep tests quick


def _vault(plaintext: bytes = b"secret database bytes") -> tuple[bytes, str]:
    keys, recovery = crypto.create_keys("correct horse", params=FAST)
    return crypto.seal(plaintext, keys), recovery


def test_round_trip_with_password() -> None:
    blob, _ = _vault()
    plaintext, keys = crypto.open_with_password(blob, "correct horse")
    assert plaintext == b"secret database bytes"
    assert len(keys.data_key) == 32


def test_plaintext_never_appears_in_file() -> None:
    blob, recovery = _vault(b"Demo-Passw0rd! super-secret")
    assert b"Demo-Passw0rd" not in blob
    assert b"correct horse" not in blob
    assert recovery.replace("-", "").encode() not in blob


def test_wrong_password() -> None:
    blob, _ = _vault()
    with pytest.raises(WrongPasswordError):
        crypto.open_with_password(blob, "wrong")


def test_empty_password_rejected() -> None:
    with pytest.raises(ValueError):
        crypto.create_keys("", params=FAST)


def test_recovery_key_opens_vault_in_any_format() -> None:
    blob, recovery = _vault()
    assert len(recovery) == 39 and recovery.count("-") == 7
    for variant in (
        recovery,
        recovery.lower(),
        recovery.replace("-", " "),
        recovery.replace("-", ""),
    ):
        plaintext, _ = crypto.open_with_recovery_key(blob, variant)
        assert plaintext == b"secret database bytes"


def test_wrong_recovery_key() -> None:
    blob, _ = _vault()
    other = crypto.new_recovery_key()
    with pytest.raises(WrongPasswordError, match="recovery key"):
        crypto.open_with_recovery_key(blob, other)
    with pytest.raises(WrongPasswordError):
        crypto.open_with_recovery_key(blob, "too-short")


def test_change_password_keeps_recovery_key_and_rotates_data_key() -> None:
    blob, recovery = _vault()
    _, keys = crypto.open_with_password(blob, "correct horse")
    new_keys = crypto.with_new_password(keys, "new password")
    assert bytes(new_keys.data_key) != bytes(keys.data_key)
    assert new_keys.vault_id == keys.vault_id
    blob2 = crypto.seal(b"x", new_keys)
    with pytest.raises(WrongPasswordError):
        crypto.open_with_password(blob2, "correct horse")
    assert crypto.open_with_password(blob2, "new password")[0] == b"x"
    assert crypto.open_with_recovery_key(blob2, recovery)[0] == b"x"
    # Someone who knew the old password only ever had the OLD data key:
    with pytest.raises(crypto.OtherVaultError):
        crypto.open_with_data_key(blob2, keys.data_key)


def test_new_recovery_key_replaces_old_and_rotates_data_key() -> None:
    blob, old = _vault()
    _, keys = crypto.open_with_password(blob, "correct horse")
    new_keys, new = crypto.with_new_recovery_key(keys)
    assert bytes(new_keys.data_key) != bytes(keys.data_key)
    blob2 = crypto.seal(b"x", new_keys)
    with pytest.raises(WrongPasswordError):
        crypto.open_with_recovery_key(blob2, old)
    assert crypto.open_with_recovery_key(blob2, new)[0] == b"x"
    assert crypto.open_with_password(blob2, "correct horse")[0] == b"x"
    # The original keys are untouched until the caller switches to the new ones.
    assert crypto.open_with_recovery_key(crypto.seal(b"y", keys), old)[0] == b"y"


def test_each_save_uses_a_fresh_nonce() -> None:
    keys, _ = crypto.create_keys("pw", params=FAST)
    assert crypto.seal(b"same", keys) != crypto.seal(b"same", keys)


@pytest.mark.parametrize("position", ["header", "body"])
def test_tampering_is_detected(position: str) -> None:
    blob = bytearray(_vault()[0])
    # Flip one byte inside the authenticated header, or inside the encrypted body.
    index = blob.index(b'"cipher"') + 2 if position == "header" else len(blob) - 5
    blob[index] ^= 0x01
    with pytest.raises((CorruptVaultError, WrongPasswordError)):
        crypto.open_with_password(bytes(blob), "correct horse")


def test_truncated_or_foreign_files() -> None:
    blob, _ = _vault()
    with pytest.raises(CorruptVaultError):
        crypto.open_with_password(blob[:40], "correct horse")
    with pytest.raises(CorruptVaultError):
        crypto.open_with_password(b"SQLite format 3\x00" + b"\x00" * 100, "x")
    newer = b"MYSAFE\x00\x09" + blob[8:]
    with pytest.raises(UnsupportedVaultError):
        crypto.open_with_password(newer, "correct horse")


def test_copies_open_with_current_or_older_data_keys() -> None:
    blob, _ = _vault()
    _, a = crypto.open_with_password(blob, "correct horse")
    newer = crypto.with_new_password(a, "new password")
    newer_blob = crypto.seal(b"x", newer)
    assert crypto.open_with_data_key(newer_blob, newer.data_key)[0] == b"x"
    # An old copy still opens with the old key kept in the history.
    assert (
        crypto.open_with_data_key(blob, newer.data_key, older_keys=(bytes(a.data_key),))[0]
        == b"secret database bytes"
    )
    other, _ = crypto.create_keys("correct horse", params=FAST)
    with pytest.raises(crypto.OtherVaultError):
        crypto.open_with_data_key(newer_blob, other.data_key)
    assert crypto.peek_vault_id(newer_blob) == a.vault_id != other.vault_id


def test_wipe_and_repr_do_not_leak() -> None:
    keys, _ = crypto.create_keys("pw", params=FAST)
    assert "bytearray" not in repr(keys) and "salt" not in repr(keys)
    keys.wipe()
    assert bytes(keys.data_key) == bytes(32)


def test_default_cost_is_strong() -> None:
    assert crypto.DEFAULT_KDF.memory_kib >= 64 * 1024
    assert crypto.DEFAULT_KDF.iterations >= 3


def test_recovery_key_problem_explains_typos() -> None:
    key = crypto.new_recovery_key()
    assert crypto.recovery_key_problem(key) is None
    assert crypto.recovery_key_problem(key.lower().replace("-", " ")) is None
    assert crypto.recovery_key_problem("") == "Enter your recovery key."
    assert "you typed 4" in (crypto.recovery_key_problem("ABCD") or "")
    assert "“9”" in (crypto.recovery_key_problem(key[:-1] + "9") or "")


def test_password_is_unicode_normalised() -> None:
    decomposed = unicodedata.normalize("NFD", "şifre-ğüç 1234")
    composed = unicodedata.normalize("NFC", "şifre-ğüç 1234")
    assert decomposed != composed
    keys, _ = crypto.create_keys(decomposed, params=FAST)
    assert crypto.open_with_password(crypto.seal(b"x", keys), composed)[0] == b"x"


@pytest.mark.parametrize(
    "params",
    [
        {"m": 2**31, "t": 3, "p": 4},
        {"m": 65536, "t": 10**6, "p": 4},
        {"m": 65536, "t": 3, "p": 10**4},
        {"m": 1024, "t": 3, "p": 4},
        {"m": "65536", "t": 3, "p": 4},
        {"m": True, "t": 3, "p": 4},
        [65536, 3, 4],
    ],
)
def test_kdf_settings_from_a_file_are_bounded(params: object) -> None:
    with pytest.raises(CorruptVaultError):
        KdfParams.from_dict(params)


def _with_header(blob: bytes, change: Callable[[dict[str, Any]], object]) -> bytes:
    header, _raw, nonce, body = crypto.read_header(blob)
    change(header)
    raw = json.dumps(header).encode()
    return crypto.MAGIC + struct.pack(">I", len(raw)) + raw + nonce + body


@pytest.mark.parametrize(
    "change",
    [
        lambda h: h.pop("password"),
        lambda h: h["password"].update(salt="!!"),
        lambda h: h["password"].update(salt="AAAA"),
        lambda h: h["password"].update(ephemeral=5),
        lambda h: h.update(kdf_params=[1]),
        lambda h: h.update(kdf_params={"m": 2**31, "t": 3, "p": 4}),
        lambda h: h.update(kdf="pbkdf2"),
        lambda h: h.update(version="2"),
    ],
)
def test_damaged_header_is_reported_not_crashing(
    change: Callable[[dict[str, Any]], object],
) -> None:
    blob, _ = _vault()
    with pytest.raises(CorruptVaultError):
        crypto.open_with_password(_with_header(blob, change), "correct horse")


def test_old_format_vault_opens_and_upgrades() -> None:
    """Format 1 (symmetric key slots) can still be opened, then gets new keys."""
    data_key = bytearray(os.urandom(32))
    recovery = crypto.new_recovery_key()

    def slot(secret: bytes, aad: bytes) -> dict[str, str]:
        salt, nonce = os.urandom(16), os.urandom(12)
        wrapped = AESGCM(crypto._derive(secret, salt, FAST)).encrypt(nonce, bytes(data_key), aad)
        return {"salt": crypto._b64(salt), "nonce": crypto._b64(nonce), "key": crypto._b64(wrapped)}

    header = {
        "version": 1,
        "cipher": "AES-256-GCM",
        "kdf": "argon2id",
        "kdf_params": FAST.to_dict(),
        "password": slot(b"old pw 12345", crypto._AAD_PASSWORD),
        "recovery": slot(crypto.normalize_recovery_key(recovery), crypto._AAD_RECOVERY),
        "keys_updated_at": 1_700_000_000,
    }
    raw = json.dumps(header).encode()
    nonce = os.urandom(12)
    body = AESGCM(bytes(data_key)).encrypt(nonce, b"v1 database", crypto.MAGIC + raw)
    blob = crypto.MAGIC + struct.pack(">I", len(raw)) + raw + nonce + body

    plaintext, keys = crypto.open_with_password(blob, "old pw 12345")
    assert plaintext == b"v1 database" and keys.version == 1
    assert crypto.open_with_recovery_key(blob, recovery)[0] == b"v1 database"
    with pytest.raises(UnsupportedVaultError):
        crypto.seal(b"x", keys)  # must be upgraded before saving
    new_keys, new_recovery = crypto.upgraded(keys, "old pw 12345")
    upgraded_blob = crypto.seal(plaintext, new_keys)
    assert crypto.open_with_password(upgraded_blob, "old pw 12345")[0] == b"v1 database"
    assert crypto.open_with_recovery_key(upgraded_blob, new_recovery)[0] == b"v1 database"
    assert bytes(new_keys.data_key) != bytes(data_key)
