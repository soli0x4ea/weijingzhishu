"""DLC Interaction — Command system (P3-01~03)."""
from __future__ import annotations

import json, os
from dataclasses import dataclass, field

from dlc.engine.entity import EntityState
from dlc.engine.modifier import apply_modifier
from dlc.engine.narrator import render_event, render_command_narrative


# ═══════════════════════════════════════════════════════════════
# P3-01: Command config loader
# ═══════════════════════════════════════════════════════════════

@dataclass
class CommandConfig:
    id: str = ""
    triggers: list = field(default_factory=list)
    description: str = ""
    effects: list = field(default_factory=list)
    cooldown_seconds: int = 0
    meta: dict = field(default_factory=dict)  # v1.1: extended fields


@dataclass
class CommandSet:
    commands: list[CommandConfig] = field(default_factory=list)


class CommandLoader:

    def __init__(self, interaction_dir: str):
        self._dir = interaction_dir

    def load(self) -> CommandSet:
        path = os.path.join(self._dir, "commands.json")
        if not os.path.isfile(path):
            return CommandSet()
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)

        cmds = []
        for c in raw.get("commands", []):
            # v1.1: name/id aliases
            cid = c.get("id") or c.get("name", "")
            # v1.1: triggers/aliases aliases
            triggers = c.get("triggers") or c.get("aliases", [])
            # v1.1: effects/modifier aliases
            effects = c.get("effects")
            if effects is None:
                mod_id = c.get("modifier") or c.get("modifier_id")
                effects = [{"type": "modifier", "modifier_id": mod_id}] if mod_id else []

            # v1.1: preserve extended fields in meta
            standard_keys = {"id", "name", "triggers", "aliases", "effects",
                             "modifier", "modifier_id", "description", "cooldown_seconds"}
            meta = {k: v for k, v in c.items() if k not in standard_keys}

            cmds.append(CommandConfig(
                id=cid, triggers=triggers,
                description=c.get("description", ""),
                effects=effects,
                cooldown_seconds=c.get("cooldown_seconds", 0),
                meta=meta,
            ))

        return CommandSet(commands=cmds)


# ═══════════════════════════════════════════════════════════════
# P3-02: Trigger word matching
# ═══════════════════════════════════════════════════════════════

def match_command(user_input: str, cmd_set: CommandSet) -> CommandConfig | None:
    """Find the command whose longest trigger appears in user_input.

    Uses longest-trigger-first to prevent partial matches:
      "释放刺激" matches "释放刺激" (4 chars) over "刺激" (2 chars).
      "解除捆绑" matches "解除捆绑" (4 chars) over "捆绑" (2 chars).

    Returns None if no match found.
    """
    text = user_input.lower()
    best_cmd = None
    best_len = 0
    for cmd in cmd_set.commands:
        for trigger in cmd.triggers:
            t = trigger.lower()
            if t in text and len(t) > best_len:
                best_len = len(t)
                best_cmd = cmd
    return best_cmd


# ═══════════════════════════════════════════════════════════════
# P3-03: Command effect executor
# ═══════════════════════════════════════════════════════════════

@dataclass
class CommandResult:
    command_id: str = ""
    success: bool = False
    output: str | None = None
    error: str = ""


def execute_command(
    effect: dict,
    state: EntityState,
    modifiers_cfg: dict,
    narratives_cfg: dict,
    entity_cfg: dict | None = None,
) -> CommandResult:
    """Execute a single command effect against the runtime state.

    Supports 4 effect types:
    - modifier: apply a modifier by id
    - narrative: render a narrative event
    - state: direct flag_set/flag_unset
    - command_narrative (v2.5.0): assemble narrative via command pipeline
    """
    etype = effect.get("type", "")
    result = CommandResult()

    try:
        if etype == "modifier":
            mod_id = effect["modifier_id"]
            mod = modifiers_cfg.get(mod_id)
            if not mod:
                return CommandResult(success=False, error=f"modifier {mod_id} not found")
            intensity = effect.get("intensity", 1.0)
            r = apply_modifier(state, mod, intensity=float(intensity), entity_cfg=entity_cfg)
            result.success = r.applied
            result.output = r.note

        elif etype == "command_narrative":
            # v2.5.0: command-driven narrative assembly
            cmd_id = effect.get("command_id", "")
            extra = effect.get("vars", {})
            text = render_command_narrative(cmd_id, state, narratives_cfg, **extra)
            result.success = bool(text)
            result.output = text

        elif etype == "narrative":
            event_id = effect["event_id"]
            text = render_event(event_id, narratives_cfg, "warning", state)
            result.success = bool(text)
            result.output = text

        elif etype == "state":
            action = effect.get("action")
            flag = effect.get("flag", "")
            if action == "flag_set" and flag:
                state.flags[flag] = 1
                result.success = True
                result.output = f"flag_set: {flag}=1"
            elif action == "flag_unset" and flag:
                state.flags[flag] = 0
                result.success = True
                result.output = f"flag_unset: {flag}=0"
            else:
                result.success = False
                result.error = f"unknown state action: {action}"

        else:
            result.error = f"unknown effect type: {etype}"

    except Exception as e:
        result.success = False
        result.error = str(e)

    return result


# ═══════════════════════════════════════════════════════════════
# P3-04: Command cooldown
# ═══════════════════════════════════════════════════════════════

_COOLDOWNS: dict[str, float] = {}

def _mark_used(cmd_id: str, tick: float | int = 0) -> None:
    _COOLDOWNS[cmd_id] = float(tick)

def _is_cooling(cmd: CommandConfig, tick: float | int = 0) -> bool:
    if cmd.cooldown_seconds <= 0:
        return False
    last = _COOLDOWNS.get(cmd.id)
    if last is None:
        return False
    return (float(tick) - last) < cmd.cooldown_seconds


# ═══════════════════════════════════════════════════════════════
# P3-05: Command prefix parsing
# ═══════════════════════════════════════════════════════════════

def parse_input(user_input: str, cmd_set: CommandSet) -> tuple[CommandConfig | None, str]:
    """Parse user input. Supports /command format and natural language.

    Returns (matched_command, remaining_args_string).
    """
    text = user_input.strip()
    if text.startswith("/"):
        # Explicit command: /状态 args
        parts = text[1:].split(maxsplit=1)
        cmd_name = parts[0]
        args = parts[1] if len(parts) > 1 else ""
        # Match by trigger or id
        for cmd in cmd_set.commands:
            if cmd_name in cmd.triggers or cmd_name == cmd.id:
                return cmd, args
        return None, ""
    else:
        # Natural language match
        cmd = match_command(text, cmd_set)
        return cmd, text


# ═══════════════════════════════════════════════════════════════
# P3-06: Help system
# ═══════════════════════════════════════════════════════════════

def generate_help(cmd_set: CommandSet) -> str:
    """Generate help text listing all available commands."""
    lines = ["[可用命令]"]
    for cmd in cmd_set.commands:
        triggers = ", ".join(cmd.triggers[:3])
        cd = f" (冷却{cmd.cooldown_seconds}s)" if cmd.cooldown_seconds else ""
        lines.append(f"- /{cmd.id} | {triggers} | {cmd.description}{cd}")
    return "\n".join(lines)
