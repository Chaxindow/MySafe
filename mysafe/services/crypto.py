"""Vault encryption: master password + recovery key → data key → AES-256-GCM.

File layout (``vault.mysafe``)::

    MAGIC (8 bytes) | header length (4 bytes, big endian) | header (UTF-8 JSON)
    | body nonce (12 bytes) | body ciphertext (AES-256-GCM, MAGIC + header used as AAD)

* A random 256-bit **data key** encrypts the body (the SQLite database).
* The header holds two **key slots**, one for the master password and one for the
  recovery key. Each slot is a small public-key "envelope" (X25519 + HKDF + AES-GCM):

  - The slot's secret (password or recovery key) is stretched with **Argon2id** into an
    X25519 private key; only its *public* key is stored in the header.
  - The data key is encrypted to that public key with a fresh ephemeral key.

  Because sealing an envelope only needs the public key, MySafe can switch to a **new
  data key** whenever the password or the recovery key changes, without knowing the other
  secret. Old copies (backups, an un-synced USB stick) then no longer help someone who knew
  the old password: what they could open was an old data key, not the current one.
* The header is authenticated (AAD), so changing it makes decryption fail.
* Every header value is checked before use, so a damaged or hostile file cannot make the
  app hang (e.g. absurd Argon2 settings) or crash.

Format version 1 (before key rotation) can still be opened; `Vault` upgrades it.
Only audited primitives from the ``cryptography`` package are used.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import secrets
import struct
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

MAGIC = b"MYSAFE\x00\x01"
FORMAT_VERSION = 2
LEGACY_VERSION = 1  # symmetric slots, no key rotation (opened, then upgraded)
KEY_BYTES = 32
NONCE_BYTES = 12
SALT_BYTES = 16
TAG_BYTES = 16
RECOVERY_KEY_BYTES = 20  # 160 bits → 32 base32 characters
MAX_HEADER_BYTES = 64 * 1024
_AAD_PASSWORD = b"mysafe:wrap:password"
_AAD_RECOVERY = b"mysafe:wrap:recovery"
_B32 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
_DAMAGED = "The vault file is damaged or was modified."


@dataclass(frozen=True, slots=True)
class KdfParams:
    """Argon2id cost. Defaults take roughly 0.2-0.5 s on a normal PC (slows down guessing)."""

    memory_kib: int = 64 * 1024
    iterations: int = 3
    lanes: int = 4

    def to_dict(self) -> dict[str, int]:
        return {"m": self.memory_kib, "t": self.iterations, "p": self.lanes}

    def at_least(self, other: KdfParams) -> bool:
        return (
            self.memory_kib >= other.memory_kib
            and self.iterations >= other.iterations
            and self.lanes >= other.lanes
        )

    @classmethod
    def from_dict(cls, data: object) -> KdfParams:
        """Read and bound-check settings from a file (a hostile file can't freeze the app)."""
        if not isinstance(data, dict):
            raise CorruptVaultError(_DAMAGED)
        values = [data.get(key) for key in ("m", "t", "p")]
        if any(type(value) is not int for value in values):
            raise CorruptVaultError(_DAMAGED)
        params = cls(*values)  # type: ignore[arg-type]
        if not (
            MIN_KDF.memory_kib <= params.memory_kib <= MAX_KDF.memory_kib
            and MIN_KDF.iterations <= params.iterations <= MAX_KDF.iterations
            and MIN_KDF.lanes <= params.lanes <= MAX_KDF.lanes
        ):
            raise CorruptVaultError("The vault's key settings are invalid.")
        return params


DEFAULT_KDF = KdfParams()
MIN_KDF = KdfParams(8 * 1024, 1, 1)  # tests use this; real vaults use DEFAULT_KDF
MAX_KDF = KdfParams(1024 * 1024, 20, 16)  # 1 GiB, far above anything MySafe writes


class VaultCryptoError(Exception):
    """Base class for vault encryption errors (messages never contain secrets)."""


class WrongPasswordError(VaultCryptoError):
    def __init__(self, what: str = "password") -> None:
        super().__init__(f"Wrong {what}.")
        self.what = what


class CorruptVaultError(VaultCryptoError):
    pass


class UnsupportedVaultError(VaultCryptoError):
    pass


class OtherVaultError(VaultCryptoError):
    """The file is a MySafe vault, but not a copy of this one."""


class NeedsPasswordError(VaultCryptoError):
    """A copy of this vault whose keys were changed elsewhere: its own password is needed."""


@dataclass(slots=True)
class VaultKeys:
    """The unlocked data key plus the (non-secret) header that wraps it."""

    data_key: bytearray = field(repr=False)
    header: dict[str, Any] = field(repr=False)

    @property
    def version(self) -> int:
        return int(self.header.get("version", FORMAT_VERSION))

    @property
    def vault_id(self) -> str:
        return str(self.header.get("vault_id", ""))

    def copy(self) -> VaultKeys:
        return VaultKeys(bytearray(self.data_key), json.loads(json.dumps(self.header)))

    def replace_with(self, other: VaultKeys) -> None:
        """Take over `other`'s data key and header, in place (wipes the old key)."""
        self.wipe()
        self.data_key[:] = other.data_key
        self.header.clear()
        self.header.update(json.loads(json.dumps(other.header)))

    def wipe(self) -> None:
        """Overwrite the data key in memory (best effort; Python may keep other copies)."""
        for i in range(len(self.data_key)):
            self.data_key[i] = 0


# --------------------------------------------------------------------- helpers


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _unb64(value: object, size: int | None = None) -> bytes:
    if not isinstance(value, str):
        raise CorruptVaultError(_DAMAGED)
    try:
        data = base64.b64decode(value.encode("ascii"), validate=True)
    except (binascii.Error, UnicodeEncodeError, ValueError) as exc:
        raise CorruptVaultError(_DAMAGED) from exc
    if size is not None and len(data) != size:
        raise CorruptVaultError(_DAMAGED)
    return data


def _derive(secret: bytes, salt: bytes, params: KdfParams) -> bytes:
    return Argon2id(
        salt=salt,
        length=KEY_BYTES,
        iterations=params.iterations,
        lanes=params.lanes,
        memory_cost=params.memory_kib,
    ).derive(secret)


def _raw(public: X25519PublicKey) -> bytes:
    return public.public_bytes(Encoding.Raw, PublicFormat.Raw)


def _envelope_key(shared: bytes, ephemeral: bytes, recipient: bytes, aad: bytes) -> bytes:
    if shared == bytes(len(shared)):  # low-order point: refuse
        raise CorruptVaultError(_DAMAGED)
    return HKDF(
        algorithm=hashes.SHA256(), length=KEY_BYTES, salt=ephemeral + recipient, info=aad
    ).derive(shared)


def _new_slot(
    secret: bytes, data_key: bytes | bytearray, params: KdfParams, aad: bytes
) -> dict[str, Any]:
    """A key slot for a (new) secret: stores salt + public key + the sealed data key."""
    salt = os.urandom(SALT_BYTES)
    private = X25519PrivateKey.from_private_bytes(_derive(secret, salt, params))
    slot = {"salt": _b64(salt), "public": _b64(_raw(private.public_key()))}
    slot.update(_seal_to(slot, data_key, aad))
    return slot


def _seal_to(slot: dict[str, Any], data_key: bytes | bytearray, aad: bytes) -> dict[str, str]:
    """Seal a data key to an existing slot's public key (no secret needed)."""
    recipient = _unb64(slot["public"], KEY_BYTES)
    ephemeral = X25519PrivateKey.generate()
    eph_raw = _raw(ephemeral.public_key())
    shared = ephemeral.exchange(X25519PublicKey.from_public_bytes(recipient))
    nonce = os.urandom(NONCE_BYTES)
    sealed = AESGCM(_envelope_key(shared, eph_raw, recipient, aad)).encrypt(
        nonce, bytes(data_key), aad
    )
    return {"ephemeral": _b64(eph_raw), "nonce": _b64(nonce), "key": _b64(sealed)}


def _open_slot(secret: bytes, slot: dict[str, Any], params: KdfParams, aad: bytes) -> bytearray:
    private = X25519PrivateKey.from_private_bytes(
        _derive(secret, _unb64(slot["salt"], SALT_BYTES), params)
    )
    recipient = _unb64(slot["public"], KEY_BYTES)
    if not secrets.compare_digest(_raw(private.public_key()), recipient):
        raise WrongPasswordError()
    eph_raw = _unb64(slot["ephemeral"], KEY_BYTES)
    try:
        shared = private.exchange(X25519PublicKey.from_public_bytes(eph_raw))
    except ValueError as exc:
        raise CorruptVaultError(_DAMAGED) from exc
    try:
        key = AESGCM(_envelope_key(shared, eph_raw, recipient, aad)).decrypt(
            _unb64(slot["nonce"], NONCE_BYTES), _unb64(slot["key"]), aad
        )
    except InvalidTag as exc:
        raise CorruptVaultError(_DAMAGED) from exc
    if len(key) != KEY_BYTES:
        raise CorruptVaultError(_DAMAGED)
    return bytearray(key)


def _open_legacy_slot(
    secret: bytes, slot: dict[str, Any], params: KdfParams, aad: bytes
) -> bytearray:
    """Format 1: the data key wrapped directly with the Argon2id key."""
    kek = _derive(secret, _unb64(slot["salt"], SALT_BYTES), params)
    try:
        key = AESGCM(kek).decrypt(
            _unb64(slot["nonce"], NONCE_BYTES), _unb64(slot["key"], KEY_BYTES + TAG_BYTES), aad
        )
    except InvalidTag as exc:
        raise WrongPasswordError() from exc
    return bytearray(key)


def password_bytes(password: str) -> bytes:
    """The password as bytes, Unicode-normalised (so "ş" typed anywhere gives the same bytes)."""
    if not password:
        raise ValueError("The master password cannot be empty")
    return unicodedata.normalize("NFC", password).encode("utf-8")


# ---------------------------------------------------------------- recovery key


def new_recovery_key() -> str:
    """A random recovery key formatted for writing on paper: XXXX-XXXX-…-XXXX (8 groups)."""
    raw = secrets.token_bytes(RECOVERY_KEY_BYTES)
    text = base64.b32encode(raw).decode("ascii")  # 32 chars, no padding for 20 bytes
    return "-".join(text[i : i + 4] for i in range(0, len(text), 4))


def _clean_recovery_key(text: str) -> str:
    cleaned = "".join(ch for ch in text.upper() if ch.isalnum())
    # Characters that are never in a key but look like ones that are (no entropy lost).
    return cleaned.replace("0", "O").replace("1", "I").replace("8", "B")


def normalize_recovery_key(text: str) -> bytes:
    """Accept the key with or without dashes/spaces, any case; common look-alikes fixed."""
    cleaned = _clean_recovery_key(text)
    if len(cleaned) != 32 or any(ch not in _B32 for ch in cleaned):
        raise WrongPasswordError("recovery key")
    return cleaned.encode("ascii")


def recovery_key_problem(text: str) -> str | None:
    """Why `text` can't be a recovery key (wrong length / characters), or None if it could be."""
    cleaned = _clean_recovery_key(text)
    if not cleaned:
        return "Enter your recovery key."
    bad = sorted({ch for ch in cleaned if ch not in _B32})
    if bad:
        return (
            f"A recovery key only has the letters A–Z and digits 2–7; "
            f"“{''.join(bad)}” can't be part of it. Check what you typed."
        )
    if len(cleaned) != 32:
        return (
            f"A recovery key has 32 characters (8 groups of 4); you typed {len(cleaned)}. "
            "Check for a missing or extra group."
        )
    return None


# ------------------------------------------------------------------- key changes


def create_keys(password: str, *, params: KdfParams = DEFAULT_KDF) -> tuple[VaultKeys, str]:
    """New random data key, sealed for the password and a fresh recovery key."""
    recovery = new_recovery_key()
    data_key = bytearray(os.urandom(KEY_BYTES))
    header: dict[str, Any] = {
        "version": FORMAT_VERSION,
        "vault_id": secrets.token_hex(16),
        "cipher": "AES-256-GCM",
        "kdf": "argon2id",
        "kdf_params": params.to_dict(),
        "password": _new_slot(password_bytes(password), data_key, params, _AAD_PASSWORD),
        "recovery": _new_slot(normalize_recovery_key(recovery), data_key, params, _AAD_RECOVERY),
        "keys_updated_at": int(time.time()),
    }
    return VaultKeys(data_key, header), recovery


def _rotated(
    keys: VaultKeys,
    *,
    password_slot: dict[str, Any] | None = None,
    recovery_slot: dict[str, Any] | None = None,
    data_key: bytearray,
) -> VaultKeys:
    header = json.loads(json.dumps(keys.header))
    for name, aad, fresh in (
        ("password", _AAD_PASSWORD, password_slot),
        ("recovery", _AAD_RECOVERY, recovery_slot),
    ):
        if fresh is not None:
            header[name] = fresh
        else:  # keep the same secret, seal the new data key to it
            slot = {k: header[name][k] for k in ("salt", "public")}
            slot.update(_seal_to(slot, data_key, aad))
            header[name] = slot
    header["keys_updated_at"] = max(int(time.time()), keys_updated_at(keys) + 1)
    return VaultKeys(data_key, header)


def with_new_password(keys: VaultKeys, new_password: str) -> VaultKeys:
    """New keys: a new data key, the new password; the recovery key keeps working."""
    if keys.version != FORMAT_VERSION:
        raise UnsupportedVaultError("Upgrade the vault first.")
    params = KdfParams.from_dict(keys.header["kdf_params"])
    data_key = bytearray(os.urandom(KEY_BYTES))
    slot = _new_slot(password_bytes(new_password), data_key, params, _AAD_PASSWORD)
    return _rotated(keys, password_slot=slot, data_key=data_key)


def with_new_recovery_key(keys: VaultKeys) -> tuple[VaultKeys, str]:
    """New keys: a new data key and a new recovery key; the password keeps working."""
    if keys.version != FORMAT_VERSION:
        raise UnsupportedVaultError("Upgrade the vault first.")
    params = KdfParams.from_dict(keys.header["kdf_params"])
    recovery = new_recovery_key()
    data_key = bytearray(os.urandom(KEY_BYTES))
    slot = _new_slot(normalize_recovery_key(recovery), data_key, params, _AAD_RECOVERY)
    return _rotated(keys, recovery_slot=slot, data_key=data_key), recovery


def upgraded(keys: VaultKeys, password: str) -> tuple[VaultKeys, str]:
    """Format 1 → current format: new data key, same password, a NEW recovery key.

    (The old recovery key can't be carried over without knowing it.)
    """
    fresh, recovery = create_keys(password, params=DEFAULT_KDF)
    if keys.vault_id:
        fresh.header["vault_id"] = keys.vault_id
    fresh.header["keys_updated_at"] = max(
        int(fresh.header["keys_updated_at"]), keys_updated_at(keys) + 1
    )
    return fresh, recovery


# ------------------------------------------------------------------ the file


def seal(plaintext: bytes, keys: VaultKeys) -> bytes:
    """Encrypt the database bytes into the complete vault file contents."""
    if keys.version != FORMAT_VERSION:
        raise UnsupportedVaultError("Old-format keys can't be used to save; upgrade first.")
    header = json.dumps(keys.header, separators=(",", ":"), sort_keys=True).encode("utf-8")
    nonce = os.urandom(NONCE_BYTES)
    body = AESGCM(bytes(keys.data_key)).encrypt(nonce, plaintext, MAGIC + header)
    return MAGIC + struct.pack(">I", len(header)) + header + nonce + body


def _check_header(header: object) -> dict[str, Any]:
    if not isinstance(header, dict):
        raise CorruptVaultError(_DAMAGED)
    version = header.get("version")
    if type(version) is int and version > FORMAT_VERSION:
        raise UnsupportedVaultError("This vault was made by a newer MySafe. Please update.")
    if version not in (LEGACY_VERSION, FORMAT_VERSION):
        raise CorruptVaultError(_DAMAGED)
    if header.get("cipher") != "AES-256-GCM" or header.get("kdf") != "argon2id":
        raise CorruptVaultError(_DAMAGED)
    KdfParams.from_dict(header.get("kdf_params"))
    if type(header.get("keys_updated_at", 0)) is not int:
        raise CorruptVaultError(_DAMAGED)
    if version == FORMAT_VERSION and not isinstance(header.get("vault_id"), str):
        raise CorruptVaultError(_DAMAGED)
    fields = (
        ("salt", "public", "ephemeral", "nonce", "key")
        if version == FORMAT_VERSION
        else ("salt", "nonce", "key")
    )
    for name in ("password", "recovery"):
        slot = header.get(name)
        if not isinstance(slot, dict) or any(not isinstance(slot.get(f), str) for f in fields):
            raise CorruptVaultError(_DAMAGED)
    return header


def read_header(blob: bytes) -> tuple[dict[str, Any], bytes, bytes, bytes]:
    """Split a vault file into (checked header, raw header bytes, nonce, ciphertext)."""
    if len(blob) < len(MAGIC) + 4 or not blob.startswith(MAGIC[:6]):
        raise CorruptVaultError("This is not a MySafe vault file.")
    if blob[: len(MAGIC)] != MAGIC:
        raise UnsupportedVaultError("This vault was made by a newer MySafe. Please update.")
    (length,) = struct.unpack(">I", blob[len(MAGIC) : len(MAGIC) + 4])
    if length > MAX_HEADER_BYTES:
        raise CorruptVaultError(_DAMAGED)
    start = len(MAGIC) + 4
    raw = blob[start : start + length]
    rest = blob[start + length :]
    if len(raw) != length or len(rest) < NONCE_BYTES + TAG_BYTES:
        raise CorruptVaultError("The vault file is incomplete or damaged.")
    try:
        header = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise CorruptVaultError(_DAMAGED) from exc
    return _check_header(header), raw, rest[:NONCE_BYTES], rest[NONCE_BYTES:]


def _decrypt_body(data_key: bytes | bytearray, raw: bytes, nonce: bytes, body: bytes) -> bytes:
    try:
        return AESGCM(bytes(data_key)).decrypt(nonce, body, MAGIC + raw)
    except InvalidTag as exc:
        raise CorruptVaultError(_DAMAGED) from exc


def _open_with(blob: bytes, secret: bytes, slot_name: str, aad: bytes) -> tuple[bytes, VaultKeys]:
    header, raw, nonce, body = read_header(blob)
    params = KdfParams.from_dict(header["kdf_params"])
    opener = _open_slot if header["version"] == FORMAT_VERSION else _open_legacy_slot
    data_key = opener(secret, header[slot_name], params, aad)
    return _decrypt_body(data_key, raw, nonce, body), VaultKeys(data_key, header)


def open_with_password(blob: bytes, password: str) -> tuple[bytes, VaultKeys]:
    try:
        return _open_with(blob, password_bytes(password), "password", _AAD_PASSWORD)
    except WrongPasswordError:
        raw = password.encode("utf-8")
        if raw == password_bytes(password):
            raise
        # Format-1 vaults stored the password exactly as typed (not normalised).
        return _open_with(blob, raw, "password", _AAD_PASSWORD)


def open_with_recovery_key(blob: bytes, recovery_key: str) -> tuple[bytes, VaultKeys]:
    try:
        return _open_with(blob, normalize_recovery_key(recovery_key), "recovery", _AAD_RECOVERY)
    except WrongPasswordError as exc:
        raise WrongPasswordError("recovery key") from exc


def open_with_data_key(
    blob: bytes, data_key: bytes | bytearray, *, older_keys: tuple[bytes, ...] = ()
) -> tuple[bytes, VaultKeys]:
    """Open a copy of *this* vault (USB copy, backup) with keys this vault already knows.

    Tries the current data key, then data keys this vault used before (`older_keys`).
    Raises NeedsPasswordError if the file is a copy of this vault whose keys were changed
    elsewhere, OtherVaultError if it is a different vault.
    """
    header, raw, nonce, body = read_header(blob)
    for candidate in (bytes(data_key), *older_keys):
        try:
            plaintext = AESGCM(candidate).decrypt(nonce, body, MAGIC + raw)
        except InvalidTag:
            continue
        return plaintext, VaultKeys(bytearray(candidate), header)
    raise OtherVaultError("This vault is not a copy of yours. Use “Create USB copy” to make one.")


def peek_vault_id(blob: bytes) -> str:
    """The vault id written in a file's header (not verified: only a hint)."""
    try:
        header, *_ = read_header(blob)
    except VaultCryptoError:
        return ""
    return str(header.get("vault_id", ""))


def same_data_key(a: VaultKeys, b: VaultKeys) -> bool:
    return secrets.compare_digest(bytes(a.data_key), bytes(b.data_key))


def keys_updated_at(keys: VaultKeys) -> int:
    value = keys.header.get("keys_updated_at", 0)
    return value if type(value) is int else 0
