"""DLC Vault — Encrypted storage (P3-15~19).

Format (secrets.json.enc):
{
  "protocol": "dlc-vault/1.0",
  "algorithm": "AES-256-GCM",
  "key_derivation": "PBKDF2-HMAC-SHA256",
  "iterations": 100000,
  "salt": "<base64>",
  "data": "<base64-encoded nonce(12) + ciphertext + tag(16)>"
}
"""
from __future__ import annotations

import base64, hashlib, json, os, time
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


# ═══════════════════════════════════════════════════════════════
# P3-15: AES-256-GCM Encryption / Decryption
# ═══════════════════════════════════════════════════════════════

_NONCE_SIZE = 12  # bytes


def _encrypt(plaintext: bytes, key: bytes) -> bytes:
    """Encrypt plaintext with AES-256-GCM. Returns nonce + ciphertext + tag."""
    nonce = os.urandom(_NONCE_SIZE)
    aesgcm = AESGCM(key)
    ct = aesgcm.encrypt(nonce, plaintext, None)
    return nonce + ct


def _decrypt(ciphertext: bytes, key: bytes) -> bytes:
    """Decrypt ciphertext (nonce + ct + tag) with AES-256-GCM."""
    nonce = ciphertext[:_NONCE_SIZE]
    ct = ciphertext[_NONCE_SIZE:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ct, None)


# ═══════════════════════════════════════════════════════════════
# P3-16: PBKDF2 Key Derivation
# ═══════════════════════════════════════════════════════════════

_SALT_SIZE = 16
_KEY_SIZE = 32
_ITERATIONS = 100000


def _generate_salt() -> bytes:
    return os.urandom(_SALT_SIZE)


def _derive_key(password: str, salt: bytes) -> bytes:
    """Derive AES-256 key from password using PBKDF2-HMAC-SHA256."""
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITERATIONS, dklen=_KEY_SIZE)


# ═══════════════════════════════════════════════════════════════
# P3-17~19: Vault class
# ═══════════════════════════════════════════════════════════════

_VAULT_FILENAME = "secrets.json.enc"
_LOCK_FILENAME = ".vault_lock"


class Vault:
    """Encrypted vault for card secrets (L3)."""

    def __init__(self, vault_dir: str, max_attempts: int = 3, lockout_seconds: int = 300):
        self._dir = vault_dir
        self._path = os.path.join(vault_dir, _VAULT_FILENAME)
        self._lock_path = os.path.join(vault_dir, _LOCK_FILENAME)
        self._max_attempts = max_attempts
        self._lockout_seconds = lockout_seconds
        os.makedirs(vault_dir, exist_ok=True)

    # --- Write (P3-17) ---

    def write(self, data: dict, password: str) -> None:
        """Encrypt and write data to vault."""
        salt = _generate_salt()
        key = _derive_key(password, salt)
        plaintext = json.dumps(data, ensure_ascii=False).encode("utf-8")
        ct = _encrypt(plaintext, key)

        payload = {
            "protocol": "dlc-vault/1.0",
            "algorithm": "AES-256-GCM",
            "key_derivation": "PBKDF2-HMAC-SHA256",
            "iterations": _ITERATIONS,
            "salt": base64.b64encode(salt).decode("ascii"),
            "data": base64.b64encode(ct).decode("ascii"),
        }
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    # --- Read (P3-17 + P3-19 lockout) ---

    def read(self, password: str) -> dict | None:
        """Decrypt and return vault contents. Returns None if no vault exists."""
        if not os.path.isfile(self._path):
            return None

        # P3-19: check lockout
        self._check_lockout()

        with open(self._path, encoding="utf-8") as f:
            payload = json.load(f)

        salt = base64.b64decode(payload["salt"])
        key = _derive_key(password, salt)
        ct = base64.b64decode(payload["data"])

        try:
            plaintext = _decrypt(ct, key)
        except Exception:
            self._record_failure()
            # If this failure triggered lockout, raise PermissionError
            if self._is_locked():
                raise PermissionError(
                    f"Vault locked. Retry after {self._lockout_seconds}s"
                )
            raise ValueError("Wrong password or corrupted vault data")

        # Success: clear failure counter
        self._clear_lock()
        return json.loads(plaintext.decode("utf-8"))

    # --- Lockout (P3-19) ---

    def _check_lockout(self) -> None:
        if self._is_locked():
            lock = self._read_lock()
            raise PermissionError(
                f"Vault locked. Retry after {lock['locked_until'] - time.time():.0f}s"
            )

    def _is_locked(self) -> bool:
        if not os.path.isfile(self._lock_path):
            return False
        lock = self._read_lock()
        return lock.get("locked_until", 0) > time.time()

    def _read_lock(self) -> dict:
        with open(self._lock_path, encoding="utf-8") as f:
            return json.load(f)

    def _record_failure(self) -> None:
        lock = {"failures": 0, "locked_until": 0}
        if os.path.isfile(self._lock_path):
            with open(self._lock_path, encoding="utf-8") as f:
                lock = json.load(f)
        lock["failures"] = lock.get("failures", 0) + 1
        if lock["failures"] >= self._max_attempts:
            lock["locked_until"] = time.time() + self._lockout_seconds
        with open(self._lock_path, "w", encoding="utf-8") as f:
            json.dump(lock, f)

    def _clear_lock(self) -> None:
        if os.path.isfile(self._lock_path):
            os.remove(self._lock_path)
