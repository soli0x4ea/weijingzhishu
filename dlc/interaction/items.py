"""DLC Interaction — Item system (P3-07~14)."""
from __future__ import annotations

import json, os, time
from dataclasses import dataclass, field
from typing import Optional


# ═══════════════════════════════════════════════════════════════
# P3-13: Rarity system
# ═══════════════════════════════════════════════════════════════

RARITY_LEVELS = ["common", "uncommon", "rare", "epic", "legendary"]

RARITY_DISPLAY = {
    "common":    "普通",
    "uncommon":  "罕见",
    "rare":      "稀有",
    "epic":      "史诗",
    "legendary": "传说",
}

RARITY_ORDER = {r: i for i, r in enumerate(RARITY_LEVELS)}


def _validate_rarity(rarity: str) -> str:
    """Return rarity if valid, default to 'common' otherwise."""
    if rarity in RARITY_ORDER:
        return rarity
    return "common"


# ═══════════════════════════════════════════════════════════════
# P3-07: Item config loader
# ═══════════════════════════════════════════════════════════════

@dataclass
class ItemConfig:
    id: str = ""
    name: str = ""
    description: str = ""
    type: str = ""  # consumable / equippable / permanent
    effects: list = field(default_factory=list)
    max_quantity: int = 1
    use_cooldown_seconds: int = 0
    rarity: str = "common"

    def __post_init__(self):
        self.rarity = _validate_rarity(self.rarity)


class ItemLoader:
    def __init__(self, interaction_dir: str):
        self._dir = interaction_dir

    def load(self) -> list[ItemConfig]:
        path = os.path.join(self._dir, "items.json")
        if not os.path.isfile(path):
            return []
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)

        items = []
        for i in raw.get("items", []):
            # v1.1: effect (singular) → effects (array)
            effects = i.get("effects")
            if effects is None and "effect" in i:
                eff = i["effect"]
                effects = [eff] if isinstance(eff, dict) else eff

            # v1.1: type mapping — explicit type field takes priority
            itype = i.get("type", "")
            if itype:
                pass  # use as-is (consumable/equippable/permanent/...)
            elif "stackable" in i:
                # Infer from stackable: true→consumable, false→permanent.
                # ⚠️ equippable CANNOT be inferred from stackable alone —
                #    must have explicit type field in old format.
                itype = "consumable" if i["stackable"] else "permanent"
            else:
                itype = "consumable"  # safe default

            # v1.1: max_stack → max_quantity
            max_qty = i.get("max_quantity") or i.get("max_stack", 1)

            items.append(ItemConfig(
                id=i.get("id") or i.get("name", ""),
                name=i.get("name", i.get("id", "")),
                description=i.get("description", ""),
                type=itype,
                effects=effects or [],
                max_quantity=max_qty,
                use_cooldown_seconds=i.get("use_cooldown_seconds", 0),
                rarity=i.get("rarity", "common"),
            ))

        return items


# ═══════════════════════════════════════════════════════════════
# P3-08~12: Inventory management
# ═══════════════════════════════════════════════════════════════

class Inventory:
    """Item inventory with add/remove/use/equip, persistence, and rarity."""

    def __init__(self, state_dir: str = ""):
        self._slots: dict[str, int] = {}       # item_id → quantity
        self._equipped: dict[str, ItemConfig] = {}  # equipped items
        self._used_at: dict[str, float] = {}
        self._items: dict[str, ItemConfig] = {}
        self._active_effects: list[dict] = []    # P3-12: tracked from equipped
        self._dir = state_dir
        if state_dir:
            os.makedirs(state_dir, exist_ok=True)

    def register(self, item: ItemConfig) -> None:
        self._items[item.id] = item

    # --- CRUD ---

    def add(self, item: ItemConfig, qty: int = 1) -> int:
        self.register(item)
        current = self._slots.get(item.id, 0)
        added = min(qty, item.max_quantity - current)
        if added > 0:
            self._slots[item.id] = current + added
        return added

    def remove(self, item_id: str, qty: int = 1) -> bool:
        current = self._slots.get(item_id, 0)
        if current < qty:
            return False
        self._slots[item_id] = current - qty
        if self._slots[item_id] <= 0:
            del self._slots[item_id]
        return True

    def count(self, item_id: str) -> int:
        return self._slots.get(item_id, 0)

    # --- Use (P3-10~12) ---

    def use(self, item_id: str, _now: float | None = None) -> bool:
        """Use an item by id.

        _now: override for current timestamp (testability).
        Returns True if the use was successful.
        """
        item = self._items.get(item_id)
        if not item:
            return False

        # P3-10: consumables need inventory
        if item.type == "consumable":
            qty = self._slots.get(item_id, 0)
            if qty <= 0:
                return False

        # P3-10: cooldown check
        if item.use_cooldown_seconds > 0:
            now = _now if _now is not None else time.time()
            last = self._used_at.get(item_id, 0)
            if now - last < item.use_cooldown_seconds:
                return False
            self._used_at[item_id] = now

        # P3-10: consumable — consume 1
        if item.type == "consumable":
            self.remove(item_id, 1)

        # P3-12: equippable — toggle equip + track effects
        elif item.type == "equippable":
            # Need to own it
            if self._slots.get(item_id, 0) <= 0:
                return False
            if item_id in self._equipped:
                # Unequip
                del self._equipped[item_id]
                self._rebuild_active_effects()
            else:
                # Equip
                self._equipped[item_id] = item
                self._rebuild_active_effects()

        # P3-11: permanent — do nothing, just return success
        elif item.type == "permanent":
            self._rebuild_active_effects()  # ensure effects are active

        return True

    # --- Equip (P3-12) ---

    def is_equipped(self, item_id: str) -> bool:
        return item_id in self._equipped

    def unequip(self, item_id: str) -> None:
        if item_id in self._equipped:
            del self._equipped[item_id]
            self._rebuild_active_effects()

    def equipped(self) -> list[str]:
        return list(self._equipped.keys())

    def active_effects(self) -> list[dict]:
        """P3-12: return all effects from currently equipped items + permanent items."""
        return list(self._active_effects)

    def _rebuild_active_effects(self) -> None:
        """Rebuild active effects from equipped items."""
        effects = []
        for item in self._equipped.values():
            for e in item.effects:
                effects.append(dict(e))
        # P3-11: permanent items always contribute effects
        for item_id, item in self._items.items():
            if item.type == "permanent" and self._slots.get(item_id, 0) > 0:
                for e in item.effects:
                    effects.append(dict(e))
        self._active_effects = effects

    # --- List (P3-13 helper) ---

    def list_items(self) -> list[dict]:
        """Return a summary of all items in inventory."""
        result = []
        for item_id, qty in self._slots.items():
            item = self._items.get(item_id)
            if not item:
                continue
            result.append({
                "id": item_id,
                "name": item.name,
                "qty": qty,
                "rarity": item.rarity,
                "rarity_display": RARITY_DISPLAY.get(item.rarity, item.rarity),
                "equipped": item_id in self._equipped,
                "type": item.type,
            })
        # Sort by rarity (highest first)
        result.sort(key=lambda x: RARITY_ORDER.get(x["rarity"], 0), reverse=True)
        return result

    # --- Persistence (P3-14) ---

    def save(self) -> None:
        """Save inventory state to disk."""
        if not self._dir:
            return
        data = {
            "slots": dict(self._slots),
            "equipped": list(self._equipped.keys()),
            "used_at": dict(self._used_at),
        }
        path = os.path.join(self._dir, "inventory.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load(self) -> None:
        """Load inventory state from disk."""
        if not self._dir:
            return
        path = os.path.join(self._dir, "inventory.json")
        if not os.path.isfile(path):
            return
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        # Merge slots (skip items that exceed max_quantity after load)
        for item_id, qty in data.get("slots", {}).items():
            item = self._items.get(item_id)
            if item:
                self._slots[item_id] = min(qty, item.max_quantity)
            else:
                self._slots[item_id] = qty
        # Restore equipped
        for item_id in data.get("equipped", []):
            item = self._items.get(item_id)
            if item and item.type == "equippable":
                self._equipped[item_id] = item
        self._used_at = data.get("used_at", {})
        self._rebuild_active_effects()
