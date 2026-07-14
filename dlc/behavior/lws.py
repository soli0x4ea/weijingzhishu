"""DLC Behavior — LWS rule engine (P2-17~P2-21)."""
from __future__ import annotations

import json, os
from dataclasses import dataclass, field

from dlc.engine.entity import EntityState


class LWSLoadError(Exception):
    pass


# ═══════════════════════════════════════════════════════════════
# P2-17: Rule loader
# ═══════════════════════════════════════════════════════════════

@dataclass
class RuleConfig:
    id: str = ""
    description: str = ""
    condition: dict = field(default_factory=dict)
    template: str = ""
    priority: int = 0
    weight: float = 1.0

    def render(self, state: EntityState) -> str:
        """Interpolate {channel_name} placeholders from entity state."""
        result = self.template
        for ch, val in state.channels.items():
            result = result.replace(f"{{{ch}}}", str(val))
        for flag, val in state.flags.items():
            result = result.replace(f"{{{flag}}}", str(val))
        return result


@dataclass
class Ruleset:
    core_principles: list = field(default_factory=list)
    rules: list[RuleConfig] = field(default_factory=list)


class LWSLoader:
    """Load behavior/lws_rules.json."""

    def __init__(self, behavior_dir: str):
        self._dir = behavior_dir

    def load(self) -> Ruleset:
        path = os.path.join(self._dir, "lws_rules.json")
        if not os.path.isfile(path):
            raise LWSLoadError(f"lws_rules.json not found in {self._dir}")
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)

        rules = []
        for r in raw.get("rules", []):
            rules.append(RuleConfig(
                id=r["id"], description=r.get("description", ""),
                condition=r.get("condition", {}),
                template=r.get("template", ""),
                priority=r.get("priority", 0),
                weight=r.get("weight", 1.0),
            ))
        return Ruleset(
            core_principles=raw.get("core_principles", []),
            rules=rules,
        )


# ═══════════════════════════════════════════════════════════════
# P2-18: Condition evaluation
# ═══════════════════════════════════════════════════════════════

def evaluate_active_rules(ruleset: Ruleset, state: EntityState) -> list[RuleConfig]:
    """Evaluate all rules against entity state.
    Returns active rules sorted by priority (desc) + weight (desc). — P2-19
    """

    def _match_condition(rule: RuleConfig) -> bool:
        cond = rule.condition
        # channel_min
        for ch, min_val in cond.get("channel_min", {}).items():
            if state.channels.get(ch, 0) < min_val:
                return False
        # channel_max
        for ch, max_val in cond.get("channel_max", {}).items():
            if state.channels.get(ch, 0) > max_val:
                return False
        # flag_set
        for flag in cond.get("flag_set", []):
            if state.flags.get(flag, 0) != 1:
                return False
        # flag_unset
        for flag in cond.get("flag_unset", []):
            if state.flags.get(flag, 0) != 0:
                return False
        return True

    active = [r for r in ruleset.rules if _match_condition(r)]
    # P2-19: sort by priority desc, then weight desc
    active.sort(key=lambda r: (r.priority, r.weight), reverse=True)
    return active


# ═══════════════════════════════════════════════════════════════
# P2-20: Prompt injection + P2-21: Core principle protection
# ═══════════════════════════════════════════════════════════════

def generate_lws_prompt(ruleset: Ruleset, active_rules: list[RuleConfig],
                        state: EntityState | None = None) -> str:
    """Generate LWS prompt for LLM context injection.

    Core principles (P2-21) are always included regardless of active rules.
    Active rules are rendered with variable interpolation from entity state.
    """
    if state is None:
        state = EntityState(entity_id="_")

    lines = []

    # P2-21: Core principles always injected
    if ruleset.core_principles:
        lines.append("[核心原则]")
        for p in ruleset.core_principles:
            lines.append(f"- {p}")
        lines.append("")

    # Active rules with templates
    if active_rules:
        lines.append("[当前激活规则]")
        for r in active_rules:
            rendered = r.render(state)
            lines.append(f"- {rendered}")

    return "\n".join(lines)
