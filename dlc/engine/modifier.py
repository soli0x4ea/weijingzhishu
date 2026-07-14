"""DLC Engine — Modifier layer (P1-13 add, P1-14 set, P1-15 flag_toggle)."""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from .entity import EntityState


@dataclass
class ModifierResult:
    """Result of applying a modifier."""
    modifier_id: str = ""
    applied: bool = False
    deltas: dict[str, float] = field(default_factory=dict)
    note: str = ""


# ═══════════════════════════════════════════════════════════════
# P1-13: add effect
# P1-14: set effect
# ═══════════════════════════════════════════════════════════════

def calc_delta(effect: dict, intensity: float = 1.0) -> float:
    """Calculate the delta for a given effect config.

    delta = (base + random(0, random)) * intensity
    """
    base = float(effect.get("base", 0))
    rand = float(effect.get("random", 0))
    delta = base + (random.uniform(0, rand) if rand > 0 else 0)
    return delta * intensity


_EFFECT_EXECUTORS = {}


def _register(etype: str):
    def decorator(fn):
        _EFFECT_EXECUTORS[etype] = fn
        return fn
    return decorator


@_register("add")
def _exec_add(state: EntityState, channel: str, effect: dict, intensity: float) -> float:
    delta = calc_delta(effect, intensity)
    state.channels[channel] = state.channels.get(channel, 0.0) + delta
    return delta


@_register("set")
def _exec_set(state: EntityState, channel: str, effect: dict, intensity: float) -> float:
    delta = calc_delta(effect, intensity)
    state.channels[channel] = delta
    return delta


@_register("multiply")
def _exec_multiply(state: EntityState, channel: str, effect: dict, intensity: float) -> float:
    """Multiply channel value by (base + random) * intensity."""
    multiplier = calc_delta(effect, intensity)
    old = state.channels.get(channel, 0.0)
    state.channels[channel] = old * multiplier
    return state.channels[channel] - old


# ═══════════════════════════════════════════════════════════════
# G1: Channel value clamping
# ═══════════════════════════════════════════════════════════════

def clamp_channel(state: EntityState, channel: str, entity_cfg: dict) -> None:
    """Clip a channel value to the min/max bounds defined in entity config.

    Reads entity_cfg["channels"][channel]["min"] and ["max"].
    If both are None/absent, does nothing.
    """
    ch_cfg = (entity_cfg or {}).get("channels", {}).get(channel, {})
    min_val = ch_cfg.get("min")
    max_val = ch_cfg.get("max")
    if min_val is None and max_val is None:
        return
    current = state.channels.get(channel, 0.0)
    if min_val is not None and current < min_val:
        state.channels[channel] = float(min_val)
    elif max_val is not None and current > max_val:
        state.channels[channel] = float(max_val)


def apply_effect(
    state: EntityState,
    channel: str,
    effect: dict,
    intensity: float = 1.0,
    entity_cfg: dict | None = None,
) -> float:
    """Apply a single effect to a channel. Returns the delta applied.

    If entity_cfg is provided, clamps the channel value to its min/max
    after the effect is applied (G1).
    """
    etype = effect.get("type", "")
    executor = _EFFECT_EXECUTORS.get(etype)
    if not executor:
        return 0.0
    delta = executor(state, channel, effect, intensity)
    if entity_cfg is not None:
        clamp_channel(state, channel, entity_cfg)
    return delta


# ═══════════════════════════════════════════════════════════════
# P1-15: flag_toggle
# ═══════════════════════════════════════════════════════════════

def apply_flag_toggle(state: EntityState, flag: str) -> None:
    """Toggle a flag between 0 and 1."""
    current = state.flags.get(flag, 0)
    state.flags[flag] = 0 if current else 1


# ═══════════════════════════════════════════════════════════════
# Full modifier pipeline
# ═══════════════════════════════════════════════════════════════

def apply_modifier(
    state: EntityState,
    modifier_cfg: dict,
    intensity: float = 1.0,
    tick: int = 0,
    entity_cfg: dict | None = None,
) -> ModifierResult:
    """Apply a full modifier to entity state. Respects cooldown_ticks config.

    If entity_cfg is provided, channel values are clamped to their min/max
    after each effect is applied (G1).
    """
    result = ModifierResult(modifier_id=modifier_cfg.get("label", ""))

    # P2-04: Cooldown check
    if _is_on_cooldown(state, modifier_cfg, tick):
        result.note = "cooldown"
        return result

    # Flag toggle
    if modifier_cfg.get("type") == "flag_toggle" and "flag" in modifier_cfg:
        apply_flag_toggle(state, modifier_cfg["flag"])
        result.applied = True
        result.note = f"flag_toggle: {modifier_cfg['flag']}"
        _mark_cooldown(state, modifier_cfg, tick)
        return result

    # Channel effects
    effects = modifier_cfg.get("effects", {})
    applied_any = False
    for channel, effect_cfg in effects.items():
        delta = apply_effect(state, channel, effect_cfg, intensity, entity_cfg)
        if delta != 0.0 or ("type" in effect_cfg and effect_cfg["type"] not in ("unknown",)):
            result.deltas[channel] = delta
            applied_any = True

    result.applied = applied_any
    if applied_any:
        _mark_cooldown(state, modifier_cfg, tick)
        result.note = f"{len(result.deltas)} channel(s) updated"
    return result


# ═══════════════════════════════════════════════════════════════
# P2-01: state_set — timed state effect with auto-restore
# ═══════════════════════════════════════════════════════════════

@_register("state_set")
def _exec_state_set(state: EntityState, channel: str, effect: dict, intensity: float) -> float:
    """Set channel to a value with duration. Auto-restores original after ticks."""
    delta = calc_delta(effect, intensity)
    duration = int(effect.get("duration_ticks", 1))

    if "_state_set" not in state.meta:
        state.meta["_state_set"] = {}

    # Preserve original value if this channel is already under state_set
    existing = state.meta["_state_set"].get(channel)
    original = existing["original"] if existing else state.channels.get(channel, 0.0)

    state.meta["_state_set"][channel] = {
        "original": original,
        "remaining": duration,
    }

    state.channels[channel] = delta
    return delta


def tick_timed_effects(state: EntityState, entity_cfg: dict | None = None) -> None:
    """Decrement remaining ticks on all active state_set effects.
    Auto-restore original values when duration expires.

    If entity_cfg is provided, restored values are clamped to min/max (G1).
    """
    effects = state.meta.get("_state_set", {})
    if not effects:
        return

    expired = []
    for channel, data in list(effects.items()):
        data["remaining"] = data.get("remaining", 0) - 1
        if data["remaining"] <= 0:
            state.channels[channel] = data["original"]
            if entity_cfg is not None:
                clamp_channel(state, channel, entity_cfg)
            expired.append(channel)

    for ch in expired:
        del effects[ch]

    if not effects:
        state.meta.pop("_state_set", None)


# ═══════════════════════════════════════════════════════════════
# P2-02: batch_restore — restore N damaged channels
# ═══════════════════════════════════════════════════════════════

@_register("batch_restore")
def _exec_batch_restore(state: EntityState, channel: str, effect: dict, intensity: float) -> float:
    """Restore up to `count` channels from their state_set to original values.
    Restores oldest-affected first (FIFO order based on dict insertion).
    The `channel` parameter is ignored; works on all state_set channels.
    """
    effects = state.meta.get("_state_set", {})
    if not effects:
        return 0.0

    count = int(effect.get("count", 1))
    restored = 0

    # Restore in insertion order (oldest first)
    for ch_key in list(effects.keys()):
        if restored >= count:
            break
        data = effects[ch_key]
        state.channels[ch_key] = data["original"]
        del effects[ch_key]
        restored += 1

    if not effects:
        state.meta.pop("_state_set", None)

    return float(restored)


# ═══════════════════════════════════════════════════════════════
# P2-04: Cooldown mechanism
# ═══════════════════════════════════════════════════════════════

def _cooldown_key(modifier_cfg: dict) -> str:
    """Derive a stable cooldown key from modifier config."""
    return modifier_cfg.get("label", "") or str(id(modifier_cfg))


def _is_on_cooldown(state: EntityState, modifier_cfg: dict, tick: int) -> bool:
    """Check if this modifier is currently on cooldown."""
    cooldown_ticks = modifier_cfg.get("cooldown_ticks", 0)
    if cooldown_ticks <= 0:
        return False
    if "_cooldowns" not in state.meta:
        return False
    last_used = state.meta["_cooldowns"].get(_cooldown_key(modifier_cfg), -999)
    return (tick - last_used) < cooldown_ticks


def _mark_cooldown(state: EntityState, modifier_cfg: dict, tick: int) -> None:
    """Record the tick when this modifier was last applied."""
    if modifier_cfg.get("cooldown_ticks", 0) <= 0:
        return
    if "_cooldowns" not in state.meta:
        state.meta["_cooldowns"] = {}
    state.meta["_cooldowns"][_cooldown_key(modifier_cfg)] = tick


# ═══════════════════════════════════════════════════════════════
# P2-03: Auto-trigger modifier
# ═══════════════════════════════════════════════════════════════

def maybe_auto_trigger(
    state: EntityState,
    modifier_id: str,
    trigger_cfg: dict,
    modifiers_cfg: dict,
    tick: int = 0,
) -> ModifierResult:
    """Probabilistically auto-trigger a modifier based on trigger config.

    trigger_cfg should contain `trigger_probability` (0.0-1.0).
    Respects the modifier's cooldown_ticks.
    """
    result = ModifierResult(modifier_id=modifier_id)
    probability = float(trigger_cfg.get("trigger_probability", 0.0))

    if random.random() >= probability:
        result.note = "probability_check_failed"
        return result

    mod_cfg = modifiers_cfg.get(modifier_id)
    if not mod_cfg:
        result.note = f"modifier {modifier_id} not found"
        return result

    return apply_modifier(state, mod_cfg, tick=tick)
