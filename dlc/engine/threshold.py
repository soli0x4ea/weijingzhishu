"""DLC Engine — Threshold layer (P1-16 rising, P1-17 falling)."""
from __future__ import annotations

from dataclasses import dataclass

from .entity import EntityState


@dataclass
class ThresholdEvent:
    """A triggered threshold event."""
    threshold_id: str
    entity_id: str
    channel: str
    current_value: float
    threshold_value: float
    operator: str
    event_id: str
    event_type: str  # warning / critical / peak / clearing


# ═══════════════════════════════════════════════════════════════
# P1-16: rising detection (>=)
# P1-17: falling detection (the inverse)
# ═══════════════════════════════════════════════════════════════

_OPERATORS = {
    ">=": lambda cur, thr: cur >= thr,
    ">":  lambda cur, thr: cur > thr,
    "<=": lambda cur, thr: cur <= thr,
    "<":  lambda cur, thr: cur < thr,
    "==": lambda cur, thr: cur == thr,
}


def check_thresholds(
    state: EntityState,
    thresholds: dict[str, dict],
    tick: int = 0,
) -> list[ThresholdEvent]:
    """Check all thresholds against current entity state.

    Returns list of triggered ThresholdEvent, ordered by threshold_id.
    Respects per-threshold cooldown_ticks when tick is provided.
    """
    events = []
    for tid, tcfg in thresholds.items():
        entity = tcfg.get("entity", "")
        if entity != state.entity_id:
            continue

        channel = tcfg.get("channel", "")
        current = state.channels.get(channel)
        if current is None:
            continue

        # P2-05: Cooldown check
        if _is_threshold_on_cooldown(state, tid, tcfg, tick):
            continue

        operator = tcfg.get("operator", ">=")
        threshold_val = float(tcfg.get("value", 0))

        checker = _OPERATORS.get(operator, _OPERATORS[">="])
        if checker(current, threshold_val):
            events.append(ThresholdEvent(
                threshold_id=tid,
                entity_id=entity,
                channel=channel,
                current_value=current,
                threshold_value=threshold_val,
                operator=operator,
                event_id=tcfg["event_id"],
                event_type=tcfg.get("event_type", "warning"),
            ))
            # Mark cooldown
            _mark_threshold_cooldown(state, tid, tcfg, tick)

    return events


# ═══════════════════════════════════════════════════════════════
# P2-05: Threshold cooldown internals
# ═══════════════════════════════════════════════════════════════

def _is_threshold_on_cooldown(state: EntityState, tid: str, tcfg: dict, tick: int) -> bool:
    cooldown_ticks = tcfg.get("cooldown_ticks", 0)
    if cooldown_ticks <= 0:
        return False
    last_fired = state.meta.get("_threshold_cd", {}).get(tid, -999)
    return (tick - last_fired) < cooldown_ticks


def _mark_threshold_cooldown(state: EntityState, tid: str, tcfg: dict, tick: int) -> None:
    if tcfg.get("cooldown_ticks", 0) <= 0:
        return
    if "_threshold_cd" not in state.meta:
        state.meta["_threshold_cd"] = {}
    state.meta["_threshold_cd"][tid] = tick
