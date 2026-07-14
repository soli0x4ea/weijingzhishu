"""DLC Protocol v1.0 — Packager.

P0-27: Directory → .dlc packaging (ZIP)
P0-28: .dlc → Directory unpacking
P0-29: Single-file .dlc.json format (L0-L1)
P0-30: Optional HMAC-SHA256 signature verification
"""
from __future__ import annotations

import json, os, zipfile, hashlib, hmac


# ── P0-27: Pack directory → .dlc ──────────────────────────────

def pack(card_dir: str, output_path: str) -> str:
    """Pack a card directory into a .dlc file (ZIP archive).

    The .dlc format is a ZIP file containing all card files,
    preserving the directory structure. State files and backups
    are excluded.

    Args:
        card_dir: Absolute path to the card directory.
        output_path: Destination .dlc file path.

    Returns:
        The output_path (for chaining).

    Raises:
        FileNotFoundError: card_dir doesn't exist.
        ValueError: card_dir doesn't contain card.json.
    """
    card_dir = os.path.abspath(card_dir)
    card_json = os.path.join(card_dir, "card.json")
    if not os.path.isfile(card_json):
        raise ValueError(f"Not a valid card directory (no card.json): {card_dir}")

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(card_dir):
            # Skip state files and backups
            dirs[:] = [d for d in dirs if d not in ("state", ".backups", "__pycache__")]

            for fname in files:
                if fname.endswith(".pyc"):
                    continue
                abs_path = os.path.join(root, fname)
                rel_path = os.path.relpath(abs_path, card_dir)
                zf.write(abs_path, rel_path)

    return output_path


# ── P0-28: Unpack .dlc → Directory ───────────────────────────

def unpack(dlc_path: str, output_dir: str) -> str:
    """Unpack a .dlc file into a directory.

    Args:
        dlc_path: Path to the .dlc file.
        output_dir: Directory to extract into (created if needed).

    Returns:
        The output_dir path.

    Raises:
        FileNotFoundError: dlc_path doesn't exist.
    """
    os.makedirs(output_dir, exist_ok=True)
    output_dir = os.path.abspath(output_dir)

    with zipfile.ZipFile(dlc_path, "r") as zf:
        for entry in zf.infolist():
            # BUG-01 fix: prevent ZIP Slip — reject paths that escape output_dir
            target = os.path.normpath(os.path.join(output_dir, entry.filename))
            if not target.startswith(output_dir + os.sep) and target != output_dir:
                raise ValueError(
                    f"ZIP Slip detected: '{entry.filename}' would extract outside "
                    f"target directory '{output_dir}'"
                )
            zf.extract(entry, output_dir)

    return output_dir


# ── P0-29: Single-file .dlc.json ──────────────────────────────

def pack_single(card_dir: str, output_path: str) -> str:
    """Pack an L0/L1 card into a single .dlc.json file.

    Reads card.json and inlines all module config files into
    a single JSON wrapper. Suitable for L0-L1 cards where the
    total data fits comfortably in one file.

    Format:
        {
            "card": { ... card.json content ... },
            "configs": {
                "identity__profile": { ... profile.json ... },
                "engine__entities": { ... entities.json ... },
                ...
            }
        }

    Args:
        card_dir: Card directory.
        output_path: Destination .dlc.json file.

    Returns:
        The output_path.
    """
    card_dir = os.path.abspath(card_dir)
    card_path = os.path.join(card_dir, "card.json")

    with open(card_path, "r", encoding="utf-8") as f:
        card = json.load(f)

    configs = {}
    modules = card.get("modules", {})

    # Inline all enabled module configs
    for mod_name, mod_cfg in modules.items():
        if not mod_cfg.get("enabled", False):
            continue
        for key, rel_path in mod_cfg.items():
            if key == "enabled" or rel_path is None:
                continue
            abs_path = os.path.join(card_dir, rel_path)
            if not os.path.isfile(abs_path):
                continue
            with open(abs_path, "r", encoding="utf-8") as f:
                configs[f"{mod_name}__{key}"] = json.load(f)

    result = {
        "card": card,
        "configs": configs,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    return output_path


# ── P0-30: HMAC-SHA256 signature ──────────────────────────────

def sign_file(path: str, secret: bytes) -> str:
    """Create an HMAC-SHA256 signature for a file.

    Args:
        path: File to sign.
        secret: Secret key bytes.

    Returns:
        64-character hex signature string.
    """
    with open(path, "rb") as f:
        content = f.read()

    sig = hmac.new(secret, content, hashlib.sha256).hexdigest()
    return sig


def verify_file(path: str, signature: str, secret: bytes) -> bool:
    """Verify an HMAC-SHA256 signature for a file.

    Uses hmac.compare_digest to prevent timing attacks.

    Args:
        path: File to verify.
        signature: Expected hex signature.
        secret: Secret key bytes.

    Returns:
        True if signature matches.
    """
    expected = sign_file(path, secret)
    return hmac.compare_digest(expected, signature)
