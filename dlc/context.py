"""DLC Protocol — Runtime Context (v2.6.0).

P0-21: CardRuntimeContext.

Encapsulates card configuration + resolved configs + runtime state
into a single context object. Memory module auto-loaded when enabled.
"""
from __future__ import annotations

import os

from dlc.resolver import ConfigResolver


class CardRuntimeContext:
    """Contextual wrapper for a loaded digital life card.

    Provides:
    - Card metadata (card_id, complexity_level, etc.)
    - Config file loading via resolver
    - Shortcut properties for engine configs
    - Memory auto-loading (ChatlogStore + TimelineStore + MemorySearch)
    - Card-scoped state directory
    """

    def __init__(self, card_dir: str):
        self._card_dir = os.path.abspath(card_dir)
        self.resolver = ConfigResolver(card_dir)
        self._ensure_state_dir()
        self._chatlog = None
        self._timeline = None
        self._memory_search = None
        self._init_memory()

    # ── Card metadata ────────────────────────────────────────

    @property
    def card_id(self) -> str:
        return self.resolver.card_id

    @property
    def card(self) -> dict:
        return self.resolver.card

    @property
    def complexity_level(self) -> str:
        return self.card.get("complexity_level", "L0")

    # ── Engine config shortcuts ──────────────────────────────

    @property
    def entities(self) -> dict:
        return self._load_if_enabled("engine", "entities")

    @property
    def modifiers(self) -> dict:
        return self._load_if_enabled("engine", "modifiers")

    @property
    def thresholds(self) -> dict:
        return self._load_if_enabled("engine", "thresholds")

    @property
    def narratives(self) -> dict:
        return self._load_if_enabled("engine", "narratives")

    # ── Memory (v2.6.0) ──────────────────────────────────────

    @property
    def chatlog(self):
        """ChatlogStore instance, auto-loaded if memory.enabled."""
        return self._chatlog

    @property
    def timeline(self):
        """TimelineStore instance, auto-loaded if memory.enabled."""
        return self._timeline

    @property
    def memory_search(self):
        """MemorySearch instance, auto-loaded if memory.enabled."""
        return self._memory_search

    @property
    def memory_enabled(self) -> bool:
        return self.card.get("modules", {}).get("memory", {}).get("enabled", False)

    def _init_memory(self):
        """Auto-load memory stores if card.modules.memory.enabled."""
        if not self.memory_enabled:
            return
        from dlc.memory import ChatlogStore, TimelineStore, MemorySearch
        mem_root = os.path.join(self._card_dir, "MEMORY")
        self._chatlog = ChatlogStore(os.path.join(mem_root, "chatlog"))
        self._timeline = TimelineStore(os.path.join(mem_root, "timeline"))
        self._memory_search = MemorySearch(self._chatlog, self._timeline)

    # ── Generic config access ────────────────────────────────

    def load_engine_config(self, sub_key: str) -> dict:
        return self.resolver.load_config("engine", sub_key)

    # ── State directory ──────────────────────────────────────

    @property
    def state_dir(self) -> str:
        return self.resolver.state_dir

    # ── Internal ─────────────────────────────────────────────

    def _ensure_state_dir(self):
        os.makedirs(self.state_dir, exist_ok=True)

    def _load_if_enabled(self, module: str, sub_key: str):
        try:
            return self.resolver.load_config(module, sub_key)
        except Exception:
            return {}
