"""DLC Engine — public API."""
from __future__ import annotations

from .entity import EntityState, EntityEngine, apply_decay
from .modifier import (
    ModifierResult, calc_delta, apply_effect, apply_flag_toggle, apply_modifier,
    clamp_channel, tick_timed_effects, maybe_auto_trigger,
)
from .threshold import ThresholdEvent, check_thresholds
from .narrator import (
    render_event, render_events,
    interpolate, range_select, conditional_append, weighted_random,
    render_command_narrative,
)

__all__ = [
    "EntityState", "EntityEngine", "apply_decay",
    "ModifierResult", "calc_delta", "apply_effect", "apply_flag_toggle", "apply_modifier",
    "clamp_channel", "tick_timed_effects", "maybe_auto_trigger",
    "ThresholdEvent", "check_thresholds",
    "render_event", "render_events",
    "interpolate", "range_select", "conditional_append", "weighted_random",
    "render_command_narrative",
]
