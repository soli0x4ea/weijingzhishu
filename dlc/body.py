"""DLC Body Module — Anatomy / Zones / State management."""
from __future__ import annotations

import json, os
from dataclasses import dataclass, field
from typing import Optional


class BodyLoadError(Exception):
    """Raised when a body config file is missing or invalid."""
    pass


# ═══════════════════════════════════════════════════════════════
# Data types
# ═══════════════════════════════════════════════════════════════

@dataclass
class StateLevel:
    level: int
    name: str


@dataclass
class Region:
    id: str
    name: str
    state_levels: list[StateLevel] = field(default_factory=list)
    sensitivity: float = 0.5
    pairs_with: Optional[str] = None

    @property
    def max_level(self) -> int:
        return max((s.level for s in self.state_levels), default=0)

    @property
    def min_level(self) -> int:
        return min((s.level for s in self.state_levels), default=0)


@dataclass
class Zone:
    id: str
    name: str
    parent_region: str
    sensitivity_multiplier: float
    zone_type: str  # erogenous / ticklish / painful / special
    trigger_modifiers: list[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════
# BodyModel — mutable state container
# ═══════════════════════════════════════════════════════════════

class BodyModel:
    """Mutable body model with regions and tracked state."""

    def __init__(
        self,
        body_model: str,
        regions: dict[str, Region],
        initial_state: dict[str, int],
        decay_rate: float = 0.0,
    ):
        self.body_model = body_model
        self.regions = regions
        self.decay_rate = decay_rate
        # Initialize state from config, default to 0
        self._state: dict[str, int] = {}
        for rid in regions:
            self._state[rid] = initial_state.get(rid, 0)

    # P1-08: State CRUD -------------------------------

    def get_state(self, region_id: str) -> int:
        if region_id not in self.regions:
            raise KeyError(f"Unknown region: {region_id}")
        return self._state[region_id]

    def set_state(self, region_id: str, level: int) -> None:
        if region_id not in self.regions:
            raise KeyError(f"Unknown region: {region_id}")
        region = self.regions[region_id]
        self._state[region_id] = max(region.min_level, min(region.max_level, level))

    # P1-09: State transitions -------------------------

    def raise_state(self, region_id: str, delta: int = 1) -> None:
        """Increase state level by delta (capped at max)."""
        current = self.get_state(region_id)
        self.set_state(region_id, current + delta)

    def lower_state(self, region_id: str, delta: int = 1) -> None:
        """Decrease state level by delta (capped at min)."""
        current = self.get_state(region_id)
        self.set_state(region_id, current - delta)

    # P1-12: Symmetric pairing -------------------------

    def has_pair(self, region_id: str) -> bool:
        region = self.regions.get(region_id)
        return bool(region and region.pairs_with)

    def get_pair(self, region_id: str) -> Optional[str]:
        region = self.regions.get(region_id)
        return region.pairs_with if region else None

    @property
    def initial_state(self) -> dict[str, int]:
        return dict(self._state)


# ═══════════════════════════════════════════════════════════════
# P1-07: Anatomy loader
# ═══════════════════════════════════════════════════════════════

class AnatomyLoader:
    """Load and validate body/anatomy.json."""

    def __init__(self, body_dir: str):
        self._dir = body_dir

    def load(self) -> BodyModel:
        path = os.path.join(self._dir, "anatomy.json")
        if not os.path.isfile(path):
            raise BodyLoadError(f"anatomy.json not found in {self._dir}")
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except json.JSONDecodeError as e:
            raise BodyLoadError(f"Invalid JSON in anatomy.json: {e}") from e

        return self._parse(raw)

    def _parse(self, raw: dict) -> BodyModel:
        regions = {}
        for rdata in raw.get("regions", []):
            levels = [
                StateLevel(level=s["level"], name=s["name"])
                for s in rdata.get("state_levels", [])
            ]
            rid = rdata["id"]
            regions[rid] = Region(
                id=rid,
                name=rdata.get("name", rid),
                state_levels=levels,
                sensitivity=float(rdata.get("sensitivity", 0.5)),
                pairs_with=rdata.get("pairs_with"),
            )

        init = raw.get("initial_state", {})
        initial_state = {k: int(v) for k, v in init.items()}

        return BodyModel(
            body_model=raw.get("body_model", "default"),
            regions=regions,
            initial_state=initial_state,
            decay_rate=float(raw.get("decay_rate", 0.0)),
        )


# ═══════════════════════════════════════════════════════════════
# P1-10: Zones loader
# ═══════════════════════════════════════════════════════════════

class ZonesLoader:
    """Load and validate body/zones.json."""

    def __init__(self, body_dir: str):
        self._dir = body_dir

    def load(self) -> list[Zone]:
        path = os.path.join(self._dir, "zones.json")
        if not os.path.isfile(path):
            raise BodyLoadError(f"zones.json not found in {self._dir}")
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except json.JSONDecodeError as e:
            raise BodyLoadError(f"Invalid JSON in zones.json: {e}") from e

        return self._parse(raw)

    def _parse(self, raw: dict) -> list[Zone]:
        zones = []
        for zdata in raw.get("zones", []):
            zones.append(Zone(
                id=zdata["id"],
                name=zdata.get("name", zdata["id"]),
                parent_region=zdata["parent_region"],
                sensitivity_multiplier=float(zdata.get("sensitivity_multiplier", 1.0)),
                zone_type=zdata.get("zone_type", "special"),
                trigger_modifiers=zdata.get("trigger_modifiers", []),
            ))
        return zones


# ═══════════════════════════════════════════════════════════════
# P1-11: Zone → channel mapping
# ═══════════════════════════════════════════════════════════════

def map_zone_to_channel(zone: Zone, body: BodyModel, entity_id: str) -> str:
    """Map a body zone to an engine channel ID.

    The mapping is zone_type + parent_region based.
    Returns a channel ID string that corresponds to an engine entity channel.
    """
    if zone.parent_region not in body.regions:
        raise KeyError(f"Zone parent_region '{zone.parent_region}' not found in body model")

    # Zone type → channel suffix mapping
    type_suffix = {
        "erogenous": "v",   # pleasure / Metric V
        "ticklish":  "t",   # tickle / Sensory
        "painful":   "a",   # pain / Metric A
        "special":   "s",   # shame / Metric S
    }.get(zone.zone_type, "s")

    # Generate channel ID in the pattern used by engine entities
    # Format: <entity_prefix>_<zone_type>_<region>
    return f"{entity_id}_{type_suffix}_{zone.parent_region}"


# ═══════════════════════════════════════════════════════════════
# P1-12: Symmetric pairing sync
# ═══════════════════════════════════════════════════════════════

def sync_pair(body: BodyModel, region_id: str) -> None:
    """Synchronize the state of a paired region to its partner.

    If region A has a pairs_with partner B, this copies A's state to B.
    """
    pair_id = body.get_pair(region_id)
    if pair_id and pair_id in body.regions:
        current = body.get_state(region_id)
        body.set_state(pair_id, current)
