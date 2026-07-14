"""DLC Protocol v1.0 — Config Resolver.

P0-16: Dynamic config path resolution.

Given a card directory, resolves and loads config files based on
the module index in card.json. This replaces hardcoded paths in
the engine with card-injected paths.
"""
from __future__ import annotations

import json, os

from dlc.constants import MODULE_SUBKEYS


class ResolverError(Exception):
    """Raised when a config file cannot be found or loaded."""
    pass


class ConfigResolver:
    """Resolve and load config files from a card directory.

    Reads card.json to build a module→sub-key→path index,
    then loads config files on demand with caching.

    Usage:
        resolver = ConfigResolver("/path/to/card_dir")
        profile = resolver.load_config("identity", "profile")
    """

    def __init__(self, card_dir: str):
        self._card_dir = os.path.abspath(card_dir)
        self._cache = {}

        # Load and validate card.json
        card_path = self._resolve_path("card.json")
        with open(card_path, "r", encoding="utf-8") as f:
            self._card = json.load(f)

        # Basic validation
        required = ["card_id", "protocol_version", "modules"]
        for key in required:
            if key not in self._card:
                raise ResolverError(
                    f"card.json missing required field: {key}"
                )

        # Build the config path index from modules
        self._paths = self._build_index()

    # ── Public API ─────────────────────────────────────────────

    @property
    def card_id(self) -> str:
        return self._card["card_id"]

    @property
    def card(self) -> dict:
        return self._card

    @property
    def enabled_modules(self) -> list[str]:
        return sorted(self._paths.keys())

    @property
    def state_dir(self) -> str:
        """Card-scoped state directory."""
        d = os.path.join(self._card_dir, "state")
        os.makedirs(d, exist_ok=True)
        return d

    def load_config(self, module: str, sub_key: str) -> dict:
        """Load a config file for a module sub-key.

        Args:
            module: Module name (e.g. "identity", "engine").
            sub_key: Sub-key name (e.g. "profile", "entities").

        Returns:
            Parsed config dict.

        Raises:
            ResolverError: Module disabled, path not found, or file missing.
        """
        cache_key = f"{module}.{sub_key}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        if module not in self._paths:
            raise ResolverError(
                f"Module '{module}' is not enabled in this card"
            )

        if sub_key not in self._paths[module]:
            raise ResolverError(
                f"Sub-key '{sub_key}' not found in module '{module}'"
            )

        rel_path = self._paths[module][sub_key]
        if rel_path is None:
            raise ResolverError(
                f"Module '{module}.{sub_key}' has no path configured"
            )

        abs_path = self._resolve_path(rel_path)
        if not os.path.isfile(abs_path):
            raise ResolverError(
                f"Config file not found: {abs_path}"
            )

        with open(abs_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self._cache[cache_key] = data
        return data

    # ── Internal ──────────────────────────────────────────────

    def _resolve_path(self, rel_path: str) -> str:
        return os.path.normpath(os.path.join(self._card_dir, rel_path))

    def _build_index(self) -> dict:
        """Build { module: { sub_key: rel_path } } from card.json modules."""
        modules = self._card.get("modules", {})
        index = {}

        for mod_name, subkeys in MODULE_SUBKEYS.items():
            mod_cfg = modules.get(mod_name, {})
            if mod_cfg.get("enabled", False):
                entry = {}
                for sk in subkeys:
                    entry[sk] = mod_cfg.get(sk)
                index[mod_name] = entry

        return index
