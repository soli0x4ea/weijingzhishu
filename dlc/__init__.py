from __future__ import annotations
import sys
sys.dont_write_bytecode = True
"""DLC Protocol v1.0 — Digital Life Card Framework."""

# P0: Foundation
from dlc.loader import (
    load_card, check_version, CardConfig, CardLoadError,
    resolve_modules, detect_complexity, check_dependencies,
)
from dlc.validate import validate_card, validate_module
from dlc.resolver import ConfigResolver, ResolverError
from dlc.context import CardRuntimeContext
from dlc.persistence import StateManager
from dlc.packager import pack, unpack, pack_single, sign_file, verify_file

# P1: Identity module (L0)
from dlc.identity import (
    Profile, Appearance,
    Personality, Trait, MoralAxis,
    Speech, EmojiUsage,
    ProfileLoader, PersonalityLoader, SpeechLoader,
    generate_system_prompt, filter_forbidden_words, get_welcome_message,
    IdentityLoadError,
)

# P1: Body module (L1)
from dlc.body import (
    BodyModel, Region, StateLevel, Zone,
    AnatomyLoader, ZonesLoader,
    map_zone_to_channel, sync_pair,
    BodyLoadError,
)

# P1: Engine module (L1)
from dlc.engine import (
    EntityState, EntityEngine, apply_decay,
    ModifierResult, calc_delta, apply_effect, apply_flag_toggle, apply_modifier,
    clamp_channel, tick_timed_effects,
    ThresholdEvent, check_thresholds,
    render_event, render_events,
    interpolate, range_select, conditional_append, weighted_random,
    render_command_narrative,
)

# P2: Memory (v1.1 dual-core linear) + LWS + Scheduler
from dlc.memory import (
    ChatlogStore, TimelineStore, MemorySearch,
    import_chatlog, import_timeline, record_chat,
)
from dlc.behavior import LWSLoader, Ruleset, RuleConfig, evaluate_active_rules, generate_lws_prompt
from dlc.scheduler import ScheduleLoader, ScheduleConfig, ScheduleEngine

# P3: Interaction + Vault (L3)
from dlc.interaction import (
    CommandConfig, CommandSet, CommandLoader, CommandResult,
    match_command, execute_command, parse_input, generate_help,
    ItemConfig, ItemLoader, Inventory,
    RARITY_LEVELS, RARITY_DISPLAY,
)
from dlc.vault import Vault

__all__ = [
    # P0
    "load_card", "check_version", "CardConfig", "CardLoadError",
    "resolve_modules", "detect_complexity", "check_dependencies",
    "validate_card", "validate_module",
    "ConfigResolver", "ResolverError", "CardRuntimeContext",
    "StateManager",
    "pack", "unpack", "pack_single", "sign_file", "verify_file",
    # P1 Identity
    "Profile", "Appearance",
    "Personality", "Trait", "MoralAxis",
    "Speech", "EmojiUsage",
    "ProfileLoader", "PersonalityLoader", "SpeechLoader",
    "generate_system_prompt", "filter_forbidden_words", "get_welcome_message",
    "IdentityLoadError",
    # P1 Body
    "BodyModel", "Region", "StateLevel", "Zone",
    "AnatomyLoader", "ZonesLoader",
    "map_zone_to_channel", "sync_pair",
    "BodyLoadError",
    # P1 Engine
    "EntityState", "EntityEngine", "apply_decay",
    "ModifierResult", "calc_delta", "apply_effect", "apply_flag_toggle", "apply_modifier",
    "clamp_channel", "tick_timed_effects",
    "ThresholdEvent", "check_thresholds",
    "render_event", "render_events",
    "interpolate", "range_select", "conditional_append", "weighted_random",
    "render_command_narrative",
    # P2 Memory (v1.1)
    "ChatlogStore", "TimelineStore", "MemorySearch",
    "import_chatlog", "import_timeline", "record_chat",
    # P2 LWS
    "LWSLoader", "Ruleset", "RuleConfig", "evaluate_active_rules", "generate_lws_prompt",
    # P2 Scheduler
    "ScheduleLoader", "ScheduleConfig", "ScheduleEngine",
    # P3 Interaction
    "CommandConfig", "CommandSet", "CommandLoader", "CommandResult",
    "match_command", "execute_command", "parse_input", "generate_help",
    "ItemConfig", "ItemLoader", "Inventory",
    "RARITY_LEVELS", "RARITY_DISPLAY",
    # P3 Vault
    "Vault",
]
