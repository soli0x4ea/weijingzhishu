"""DLC Engine — Narrator layer v1.1.

P1-18: narrative rendering
P2-06: condition filtering (flag_set/flag_unset)
P2-07: priority sorting
P2-08: 3-tier narrative (mild/medium/intense)

v2.5.0: Four atomic assembly ops + command-driven narrative pipeline.
"""
from __future__ import annotations

import random as _random
from .entity import EntityState

# Severity → text tier mapping (from protocol: critical→intense, warning→medium, else→mild)
_SEVERITY_TIER = {
    "critical": "intense",
    "peak":     "intense",
    "clearing": "intense",
    "warning":  "medium",
}


# ═══════════════════════════════════════════════════════════════
# Existing: threshold-driven rendering
# ═══════════════════════════════════════════════════════════════

def _check_condition(ev_cfg: dict, state: EntityState | None) -> bool:
    """P2-06: Check if event condition (flag_set/flag_unset) is satisfied."""
    if state is None:
        return True
    condition = ev_cfg.get("condition", {})
    flag_set = condition.get("flag_set")
    flag_unset = condition.get("flag_unset")
    if flag_set and state.flags.get(flag_set, 0) != 1:
        return False
    if flag_unset and state.flags.get(flag_unset, 0) != 0:
        return False
    return True


def render_event(
    event_id: str,
    narratives: dict[str, dict],
    severity: str = "warning",
    state: EntityState | None = None,
    before_state: EntityState | None = None,
) -> str:
    """Render narrative text for a triggered threshold event.

    Lookup order (G3):
      1. narratives["events"][event_id] — single-text (backward compatible)
      2. narratives["command_assembly"][event_id] — pipeline render (G3)

    Args:
        event_id: The event ID from threshold config.
        narratives: The full narratives.json dict (with "events" and "command_assembly").
        severity: Event severity.
        state: Optional entity state for condition checking (P2-06).
        before_state: Optional snapshot before changes for {before_xxx}/{delta_xxx} (G3).

    Returns:
        Narrative text string, or "" if the event has no config, no texts,
        or its condition is not met.
    """
    # Path 1: Standard single-text event (backward compatible)
    # Handle both bare events dict and full narratives dict
    if "events" in narratives:
        events_dict = narratives["events"]
        command_assembly = narratives.get("command_assembly", {})
    else:
        events_dict = narratives
        command_assembly = {}
    ev = events_dict.get(event_id)
    if ev:
        if not _check_condition(ev, state):
            return ""
        tier = _SEVERITY_TIER.get(severity, "intense")
        texts = ev.get("texts", {})
        return texts.get(tier) or texts.get("medium") or texts.get("mild") or ""

    # Path 2: Command assembly pipeline render (G3)
    if event_id in command_assembly:
        return render_command_narrative(
            event_id, state, narratives,
            before_state=before_state,
            _event_severity=severity,
        )

    return ""


def render_events(
    events: list,
    narratives: dict[str, dict],
    state: EntityState | None = None,
    before_state: EntityState | None = None,
) -> list[str]:
    """P2-07+P2-08: Render multiple threshold events with priority sorting."""
    scored = []
    events_dict = narratives.get("events", narratives) if isinstance(narratives, dict) else {}
    for ev in events:
        ev_cfg = events_dict.get(ev.event_id, {})
        priority = ev_cfg.get("priority", 0)
        scored.append((priority, ev))

    scored.sort(key=lambda x: x[0], reverse=True)

    result = []
    for _, ev in scored:
        text = render_event(ev.event_id, narratives, ev.event_type, state,
                            before_state=before_state)
        if text:
            result.append(text)
    return result


# ═══════════════════════════════════════════════════════════════
# v2.5.0: Atomic narrative assembly operations
# ═══════════════════════════════════════════════════════════════

# ── M5-01: Variable interpolation ─────────────────────────────

def interpolate(template: str, state: EntityState | None = None,
                before_state: EntityState | None = None,
                delta_precision: int = 1,
                **extra_vars) -> str:
    """Replace {key} placeholders with values from state or extra_vars.

    Supported placeholders:
        {channel_xxx}    — value of state.channels["xxx"]
        {flag_xxx}       — value of state.flags["xxx"] or 0
        {before_xxx}     — channel xxx value BEFORE changes (G2)
        {after_xxx}      — channel xxx value AFTER changes (G2)
        {delta_xxx}      — channel xxx change: after - before (G2)
        {before}         — modifier before-value (from extra_vars)
        {after}          — modifier after-value (from extra_vars)
        {delta}          — after - before (from extra_vars)
        {n}              — count (from extra_vars, e.g. candy eaten)
        {part}           — body part name (from extra_vars)
        {variant}        — variant label (from extra_vars)
        {custom}         — any key passed via **extra_vars

    Format precision (4.1):
        {delta_xxx}   defaults to +N.M format (delta_precision decimal places).
        Pass delta_precision=0 for integer deltas like +30 instead of +30.0.

    Args:
        template: String with {placeholder} markers.
        state: EntityState for channel/flag lookups (current/after values).
        before_state: Optional snapshot before changes for {before_xxx}/{delta_xxx} (G2).
        delta_precision: Decimal places for before/after/delta values (default 1).
        **extra_vars: Additional key=value pairs for interpolation.

    Returns:
        Template with all recognized placeholders replaced.
    """
    if not template or "{" not in template:
        return template

    result = template

    # Channel values: {channel_xxx}
    if state and state.channels:
        for ch_id, val in state.channels.items():
            result = result.replace(f"{{channel_{ch_id}}}", str(val))

    # Flag values: {flag_xxx}
    if state and state.flags:
        for f_id, val in state.flags.items():
            result = result.replace(f"{{flag_{f_id}}}", str(val))

    # G2: Channel-level before/after/delta: {before_pain}, {after_pleasure}, {delta_shame}
    if before_state is not None and before_state.channels and state and state.channels:
        fmt_spec = f".{delta_precision}f"
        for ch_id in state.channels:
            before_val = before_state.channels.get(ch_id, 0.0)
            after_val = state.channels.get(ch_id, 0.0)
            delta_val = after_val - before_val
            result = result.replace(f"{{before_{ch_id}}}", f"{before_val:{fmt_spec}}")
            result = result.replace(f"{{after_{ch_id}}}", f"{after_val:{fmt_spec}}")
            result = result.replace(f"{{delta_{ch_id}}}", f"{delta_val:+{fmt_spec}}")

    # Extra vars
    for key, val in extra_vars.items():
        result = result.replace(f"{{{key}}}", str(val))

    return result


# ── M5-02: Range select ───────────────────────────────────────

def range_select(
    state: EntityState,
    channel: str,
    brackets: list,
    texts: list[str],
    before_state: EntityState | None = None,
) -> str:
    """Select text based on which bracket the channel value falls into.

    Args:
        state: EntityState whose channels[channel] is read (current/after values).
        channel: Channel name to read.
        brackets: List of [lo, hi] pairs (None = no bound).
        texts: Corresponding texts, len(texts) == len(brackets).
        before_state: Optional snapshot before changes (4.2).
            When provided, reads the channel value from before_state instead of state,
            allowing range selection based on pre-change values.

    Returns:
        The text from the first matching bracket, or "" if no match.

    Example:
        range_select(state, "candy_count",
            brackets=[[0,5], [5,10], [10,None]],
            texts=["empty", "half", "full"])
        # candy_count=3 → "empty", candy_count=7 → "half", candy_count=15 → "full"
    """
    source = before_state if before_state is not None else state
    val = (source.channels or {}).get(channel, 0)

    for i, (lo, hi) in enumerate(brackets):
        if lo is not None and val < lo:
            continue
        if hi is not None and val >= hi:
            continue
        if i < len(texts):
            return texts[i]

    return ""


# ── M5-03: Conditional append ─────────────────────────────────

def _eval_cond(cond: dict, state: EntityState) -> bool:
    """Evaluate a single condition against entity state.

    Supported conditions:
        {"channel": "xxx", "op": ">=", "value": N}
        {"channel": "xxx", "op": ">",  "value": N}
        {"channel": "xxx", "op": "<=", "value": N}
        {"channel": "xxx", "op": "<",  "value": N}
        {"channel": "xxx", "op": "==", "value": N}
        {"channel": "xxx", "op": "!=", "value": N}
        {"flag": "xxx", "set": true/false}
    """
    # Channel condition
    channel = cond.get("channel", "")
    if channel and "op" in cond:
        val = (state.channels or {}).get(channel, 0)
        op = cond["op"]
        target = cond.get("value", 0)
        if op == ">=": return val >= target
        if op == ">":  return val > target
        if op == "<=": return val <= target
        if op == "<":  return val < target
        if op == "==": return val == target
        if op == "!=": return val != target
        return False

    # Flag condition
    flag = cond.get("flag", "")
    if flag:
        expect = cond.get("set", True)
        actual = (state.flags or {}).get(flag, 0)
        return bool(actual) == bool(expect)

    return True  # empty condition = always pass


def conditional_append(
    base: str,
    conditions: list[dict],
    texts: list[str],
    state: EntityState | None = None,
    before_state: EntityState | None = None,
) -> str:
    """Append text segments when their conditions are met.

    Args:
        base: Starting text.
        conditions: List of condition dicts, one per text.
        texts: Text segments to conditionally append.
        state: EntityState for evaluation (current/after values).
        before_state: Optional snapshot before changes (4.2).
            When provided, conditions are evaluated against before_state
            instead of state, enabling "was X before the change" logic.

    Returns:
        base + all conditionally-appended texts, joined with newlines.

    Example:
        conditional_append("ate candy",
            conditions=[{"channel": "pain", "op": ">=", "value": 50},
                        {"flag": "bound", "set": True}],
            texts=["it still hurts", "bound and sweet"],
            state=state)
        # pain=60, bound=1 → "ate candy\nit still hurts\nbound and sweet"
    """
    eval_state = before_state if before_state is not None else state
    if not eval_state:
        return base

    parts = [base] if base else []
    for i, cond in enumerate(conditions):
        if i < len(texts) and _eval_cond(cond, eval_state):
            parts.append(texts[i])

    return "\n".join(p for p in parts if p)


# ── M5-04: Weighted random ────────────────────────────────────

def weighted_random(
    variants: list[dict],
) -> tuple[str, str]:
    """Randomly select a variant by weight.

    Args:
        variants: List of {"weight": N, "text": "...", "id": "..."} dicts.

    Returns:
        (text, variant_id) tuple.

    Weights are automatically normalized. Entries with weight <= 0 are excluded.
    If no valid variants exist, returns ("", "").
    """
    valid = [(v.get("weight", 1), v.get("text", ""), v.get("id", ""))
             for v in variants if v.get("weight", 0) > 0]

    if not valid:
        return "", ""

    total = sum(w for w, _, _ in valid)
    r = _random.uniform(0, total)
    cumulative = 0.0
    for w, text, vid in valid:
        cumulative += w
        if r <= cumulative:
            return text, vid

    # Fallback (floating-point edge case)
    return valid[-1][1], valid[-1][2]


# ═══════════════════════════════════════════════════════════════
# v2.5.0: Command-driven narrative pipeline
# ═══════════════════════════════════════════════════════════════

def render_command_narrative(
    cmd_id: str,
    state: EntityState,
    narratives_cfg: dict,
    before_state: EntityState | None = None,
    delta_precision: int = 1,
    **extra_vars,
) -> str:
    """Assemble narrative text for a command using the four atomic ops.

    Reads from narratives.json → "command_assembly" → cmd_id pipeline.

    Pipeline steps:
        {"op": "range", "channel": "...", "brackets": [[lo,hi],...], "texts": [...]}
        {"op": "cond",  "if": [{...},...], "texts": [...]}  — conditional_append
        {"op": "rand",  "variants": [{"weight":N,"text":"...","id":"..."},...]}
        {"op": "interp", "template": "..."}                  — interpolate
        {"op": "event",  "event_id": "...", "severity": "..."}  — threshold event

    A pipeline step may also be a plain string — treated as "interp".

    Args:
        cmd_id: Command ID (matches command_assembly key).
        state: Entity state for channel/flag reads.
        narratives_cfg: Full narratives.json dict.
        before_state: Optional snapshot before changes for {before_xxx}/{delta_xxx} (G2).
        delta_precision: Decimal places for before/after/delta values (4.1, default 1).
        **extra_vars: Extra interpolation variables.

    Returns:
        Assembled narrative text, or "" if no assembly config exists.
    """
    assembly = (narratives_cfg or {}).get("command_assembly", {})
    pipeline = assembly.get(cmd_id)

    if not pipeline:
        return ""

    lines = []
    for step in pipeline:
        # Plain string → interpolate
        if isinstance(step, str):
            text = interpolate(step, state, before_state=before_state,
                               delta_precision=delta_precision, **extra_vars)
            if text:
                lines.append(text)
            continue

        op = step.get("op", "")

        if op == "range":
            ch = step.get("channel", "")
            brackets = step.get("brackets", [])
            texts = step.get("texts", [])
            text = range_select(state, ch, brackets, texts, before_state=before_state)
            if text:
                lines.append(text)

        elif op == "cond":
            base = step.get("base", "")
            parts = [base] if base else []
            ifs = step.get("if", [])
            texts = step.get("texts", [])
            if not isinstance(ifs, list):
                ifs = [ifs]
            # 4.2: evaluate conditions against before_state when available
            eval_state = before_state if before_state is not None else state
            for i, cond in enumerate(ifs):
                if i < len(texts) and _eval_cond(cond, eval_state):
                    parts.append(texts[i])
            line = "\n".join(p for p in parts if p)
            if line:
                lines.append(line)

        elif op == "rand":
            variants = step.get("variants", [])
            text, variant_id = weighted_random(variants)
            if text:
                text = interpolate(text, state, before_state=before_state,
                                   delta_precision=delta_precision,
                                   variant=variant_id, **extra_vars)
                lines.append(text)

        elif op == "interp":
            template = step.get("template", "")
            text = interpolate(template, state, before_state=before_state,
                               delta_precision=delta_precision, **extra_vars)
            if text:
                lines.append(text)

        elif op == "event":
            event_id = step.get("event_id", "")
            severity = step.get("severity", "warning")
            text = render_event(event_id, narratives_cfg, severity, state,
                                before_state=before_state)
            if text:
                lines.append(text)

    return "\n".join(lines)
