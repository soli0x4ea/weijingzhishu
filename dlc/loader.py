"""DLC Protocol v1.0 — Card Loader.

P0-01: card.json parser
P0-02: protocol version compatibility check
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from dlc.constants import MODULE_SUBKEYS, MODULE_DEPENDENCIES, MODULE_LEVELS


class CardLoadError(Exception):
    """Raised when a card cannot be loaded or is structurally invalid."""
    pass


@dataclass
class CardConfig:
    """Parsed card.json configuration."""
    protocol_version: str
    card_id: str
    card_name: str
    complexity_level: str
    author: str
    created_at: str
    updated_at: str
    description: str = ""
    tags: list = field(default_factory=list)
    modules: dict = field(default_factory=dict)
    engine_requirements: dict = field(default_factory=dict)
    _raw: dict = field(default_factory=dict, repr=False)  # P1-22: for validate_card


# ── P0-01: card.json parser ──────────────────────────────────────

_REQUIRED_FIELDS = [
    "protocol_version", "card_id", "card_name",
    "complexity_level", "author", "created_at", "updated_at",
]


def load_card(path: str) -> CardConfig:
    """Load and parse a card.json file.

    Args:
        path: Absolute path to card.json.

    Returns:
        CardConfig with all parsed fields.

    Raises:
        CardLoadError: File missing, invalid JSON, or missing required fields.
    """
    import json
    import os

    # Resolve card.json from directory or direct path
    if os.path.isdir(path):
        path = os.path.join(path, "card.json")

    if not os.path.isfile(path):
        raise CardLoadError(f"card.json not found: {path}")

    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except json.JSONDecodeError as e:
        raise CardLoadError(f"Invalid JSON in {path}: {e}") from e

    # Support .dlc.json single-file format (P0-29):
    # { "card": {...}, "configs": {...} } → extract the card portion
    if "card" in raw and isinstance(raw["card"], dict) and "configs" in raw:
        raw = raw["card"]

    missing = [k for k in _REQUIRED_FIELDS if k not in raw]
    if missing:
        raise CardLoadError(
            f"Missing required fields in {path}: {missing}"
        )

    version_error = check_version("1.0.0", raw["protocol_version"])
    if version_error:
        raise CardLoadError(
            f"Protocol version mismatch in {path}: {version_error}"
        )

    return CardConfig(
        protocol_version=raw["protocol_version"],
        card_id=raw["card_id"],
        card_name=raw["card_name"],
        complexity_level=raw["complexity_level"],
        author=raw["author"],
        created_at=raw["created_at"],
        updated_at=raw["updated_at"],
        description=raw.get("description", ""),
        tags=raw.get("tags", []),
        modules=raw.get("modules", {}),
        engine_requirements=raw.get("engine_requirements", {}),
        _raw=raw,
    )


# ── P0-02: version compatibility check ───────────────────────────

def check_version(engine_version: str, card_version: str) -> Optional[str]:
    """Check protocol version compatibility.

    SemVer rules:
      - Same major version → compatible
      - Card major > engine major → incompatible
      - Engine major > card major → compatible (forward compat)

    Args:
        engine_version: DLC engine version string (e.g. "1.0.0").
        card_version: Card's protocol_version string.

    Returns:
        None if compatible, or an error message string if incompatible.
    """
    def _parse(v):
        parts = v.strip().split(".")
        return tuple(int(p) for p in parts[:3])

    try:
        eng = _parse(engine_version)
        card = _parse(card_version)
    except (ValueError, IndexError):
        return f"Invalid version format: engine={engine_version}, card={card_version}"

    if card[0] > eng[0]:
        return (
            f"Incompatible major version: "
            f"card requires protocol {card_version} (major {card[0]}), "
            f"engine supports {engine_version} (major {eng[0]})"
        )

    return None  # compatible


# ── P0-03: module index resolver ─────────────────────────────────

def resolve_modules(cfg: CardConfig) -> dict:
    """Extract enabled modules with their config file paths.

    Only includes modules where enabled=true. Sub-module paths
    may be None if not configured.

    Args:
        cfg: Parsed CardConfig.

    Returns:
        Dict of { module_name: { sub_key: path_or_None, ... } }
        for enabled modules only.
    """
    result = {}
    for mod_name, subkeys in MODULE_SUBKEYS.items():
        mod_cfg = cfg.modules.get(mod_name, {})
        if mod_cfg.get("enabled", False):
            entry = {}
            for sk in subkeys:
                entry[sk] = mod_cfg.get(sk)
            result[mod_name] = entry
    return result


# ── P0-04: complexity level detection ────────────────────────────

def detect_complexity(enabled_modules: dict) -> str:
    """Auto-detect complexity level from enabled modules.

    Returns the highest level whose requirements are satisfied.
    Falls back to card.json's declared level if modules don't
    cleanly match any level.

    Args:
        enabled_modules: Output of resolve_modules().

    Returns:
        Complexity level string: "L0", "L1", "L2", or "L3".
    """
    active = set(enabled_modules.keys())
    detected = "L0"
    for level, required in MODULE_LEVELS:
        if required.issubset(active):
            detected = level
    return detected


# ── P0-05: dependency integrity check ────────────────────────────

def check_dependencies(enabled_modules: dict) -> list[str]:
    """Check that all enabled modules have their dependencies satisfied.

    Args:
        enabled_modules: Output of resolve_modules().

    Returns:
        List of error messages (empty = no issues).
    """
    errors = []
    active = set(enabled_modules.keys())

    for mod, deps in MODULE_DEPENDENCIES.items():
        if mod not in active:
            continue  # module not enabled → skip dependency check
        for dep in deps:
            if dep not in active:
                errors.append(
                    f"Module '{mod}' requires '{dep}' to be enabled"
                )

    return errors
