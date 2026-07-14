"""DLC Scheduler — Task scheduling engine (P2-22~P2-27)."""
from __future__ import annotations

import json, os
from dataclasses import dataclass, field

from dlc.engine.entity import EntityState, apply_decay


# ═══════════════════════════════════════════════════════════════
# P2-22: Schedule config loader
# ═══════════════════════════════════════════════════════════════

@dataclass
class TaskConfig:
    id: str = ""
    type: str = ""
    interval_ticks: int = 1
    action: str = ""


@dataclass
class ScheduleConfig:
    tasks: list[TaskConfig] = field(default_factory=list)


class ScheduleLoader:
    def __init__(self, memory_dir: str):
        self._dir = memory_dir

    def load(self) -> ScheduleConfig:
        path = os.path.join(self._dir, "schedule.json")
        if not os.path.isfile(path):
            return ScheduleConfig()
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        tasks = [
            TaskConfig(
                id=t["id"], type=t["type"],
                interval_ticks=t.get("interval_ticks", 1),
                action=t.get("action", ""),
            )
            for t in raw.get("tasks", [])
        ]
        return ScheduleConfig(tasks=tasks)


# ═══════════════════════════════════════════════════════════════
# P2-23: Schedule engine
# ═══════════════════════════════════════════════════════════════

@dataclass
class TaskResult:
    task_id: str = ""
    fired: bool = False
    note: str = ""


class ScheduleEngine:
    """Tick-based task scheduler with built-in task dispatch.

    Supports task types: state_decay, flag_cleanup, passive_action.
    """

    def __init__(self, config: ScheduleConfig):
        self.config = config
        self.tick_count = 0
        self._last_fired: dict[str, int] = {}
        self._state: EntityState | None = None
        self._entities_cfg: dict = {}

    def set_state(self, state: EntityState, entities_cfg: dict = None):
        self._state = state
        if entities_cfg:
            self._entities_cfg = entities_cfg

    def tick(self) -> list[TaskResult]:
        self.tick_count += 1
        results = []
        for task in self.config.tasks:
            last = self._last_fired.get(task.id, -999)
            if self.tick_count - last >= task.interval_ticks:
                self._last_fired[task.id] = self.tick_count
                note = self._dispatch(task)
                results.append(TaskResult(task_id=task.id, fired=True, note=note))
            else:
                results.append(TaskResult(task_id=task.id))
        return results

    def _dispatch(self, task: TaskConfig) -> str:
        ttype = task.type
        if ttype == "state_decay" and self._state and self._entities_cfg:
            for eid, ecfg in self._entities_cfg.items():
                if self._state.entity_id == eid:
                    apply_decay(self._state, ecfg)
                    return "decay_applied"
        elif ttype == "flag_cleanup" and self._state:
            n = _task_flag_cleanup(self._state)
            return f"flags_cleaned: {n}"
        elif ttype == "passive_action":
            return f"passive: {task.action}"
        return task.type

    def is_due(self, task_id: str) -> bool:
        task = next((t for t in self.config.tasks if t.id == task_id), None)
        if not task:
            return False
        last = self._last_fired.get(task_id, -999)
        return self.tick_count - last >= task.interval_ticks


# ═══════════════════════════════════════════════════════════════
# P2-26: Built-in — flag_cleanup
# ═══════════════════════════════════════════════════════════════

def _task_flag_cleanup(state: EntityState) -> int:
    """Remove flags with value 0 or negative."""
    to_delete = [k for k, v in state.flags.items() if v <= 0]
    for k in to_delete:
        del state.flags[k]
    return len(to_delete)
