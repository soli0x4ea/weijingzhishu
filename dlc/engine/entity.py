"""DLC Engine — Entity layer.

Domain-neutral entity state management. Uses a state_dir for persistence.
"""
from __future__ import annotations

import json, os
from dataclasses import dataclass, field
from typing import Any


@dataclass
class EntityState:
    """Runtime state of a single entity."""
    entity_id: str
    channels: dict[str, float] = field(default_factory=dict)
    flags: dict[str, int] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "entity_id": self.entity_id,
            "channels": self.channels,
            "flags": self.flags,
            "meta": self.meta,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "EntityState":
        return cls(
            entity_id=data.get("entity_id", ""),
            channels=data.get("channels", {}),
            flags=data.get("flags", {}),
            meta=data.get("meta", {}),
        )


class EntityEngine:
    """Persistent entity state store keyed by entity_id."""

    def __init__(self, state_dir: str):
        self._dir = state_dir
        os.makedirs(state_dir, exist_ok=True)

    def _path(self, entity_id: str) -> str:
        return os.path.join(self._dir, f"{entity_id}.json")

    def load(self, entity_id: str) -> EntityState:
        path = self._path(entity_id)
        if not os.path.isfile(path):
            return EntityState(entity_id=entity_id)
        with open(path, "r", encoding="utf-8") as f:
            return EntityState.from_dict(json.load(f))

    def save(self, state: EntityState) -> None:
        path = self._path(state.entity_id)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state.to_dict(), f, indent=2, ensure_ascii=False)

    def exists(self, entity_id: str) -> bool:
        return os.path.isfile(self._path(entity_id))

    def list(self) -> list[str]:
        return [
            f[:-5] for f in os.listdir(self._dir)
            if f.endswith(".json")
        ]


# ═══════════════════════════════════════════════════════════════
# P1-19: Natural decay
# ═══════════════════════════════════════════════════════════════

def apply_decay(state: EntityState, entity_cfg: dict) -> None:
    """Apply per-tick decay to channels that have decay_per_tick configured."""
    channels_cfg = entity_cfg.get("channels", {})
    for ch_id, ch_cfg in channels_cfg.items():
        decay = ch_cfg.get("decay_per_tick")
        if decay is not None and decay > 0:
            current = state.channels.get(ch_id, 0)
            state.channels[ch_id] = max(0.0, current - float(decay))
