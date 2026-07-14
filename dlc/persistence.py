"""DLC Protocol v1.0 — Persistence Layer.

P0-23: StateManager — card-scoped state read/write/delete.
P0-24: export_state() — full state export to .dlc-state format.
P0-25: import_state() — restore state from exported data.
P0-26: backup/restore — manual and automatic state backup.
"""
from __future__ import annotations

import json, os, shutil
from datetime import datetime, timezone
from dlc.context import CardRuntimeContext


class StateManager:
    """Manages entity state files for a single card.

    All state files live under ctx.state_dir/<id>.json.

    Usage:
        sm = StateManager(ctx)
        sm.write("e_g", {"ch_g_a": 10, "ch_g_s": 20})
        state = sm.read("e_g")
    """

    def __init__(self, ctx: CardRuntimeContext):
        self._ctx = ctx
        self._state_dir = ctx.state_dir

    # ── P0-23: Read / Write / Delete ─────────────────────────

    def read(self, entity_id: str, default=None) -> dict | None:
        """Read entity state. Returns default (None) if not found."""
        path = self._path(entity_id)
        if not os.path.isfile(path):
            return default
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def write(self, entity_id: str, data: dict) -> str:
        """Write entity state to file atomically. Returns the file path.

        Uses temp-file + atomic rename to prevent corruption on crash.
        """
        import tempfile

        path = self._path(entity_id)
        dirname = os.path.dirname(path)

        # Write to temp file then atomically rename
        fd, tmp = tempfile.mkstemp(suffix=".json", dir=dirname)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(tmp, path)  # atomic on POSIX + Windows
        except Exception:
            os.unlink(tmp)
            raise
        return path

    def delete(self, entity_id: str) -> None:
        """Delete an entity state file. No error if not found."""
        path = self._path(entity_id)
        if os.path.isfile(path):
            os.remove(path)

    def list_states(self) -> list[str]:
        """List all entity IDs that have state files."""
        if not os.path.isdir(self._state_dir):
            return []
        ids = []
        for f in os.listdir(self._state_dir):
            if f.endswith(".json"):
                ids.append(f[:-5])  # strip .json
        return sorted(ids)

    # ── P0-24: Export ────────────────────────────────────────

    def export_state(self) -> dict:
        """Export all entity states as a serializable dict (.dlc-state format).

        Returns a dict that can be saved as JSON and imported by any
        card with matching entities.
        """
        entities = {}
        for eid in self.list_states():
            data = self.read(eid)
            if data:
                entities[eid] = data

        return {
            "protocol_version": "1.0.0",
            "card_id": self._ctx.card_id,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "entities": entities,
        }

    # ── P0-25: Import ────────────────────────────────────────

    def import_state(self, data: dict) -> None:
        """Import state from an exported .dlc-state dict.

        Writes all entity states. Existing states are overwritten.
        """
        entities = data.get("entities", {})
        for eid, state in entities.items():
            self.write(eid, state)

    # ── P0-26: Backup / Restore ──────────────────────────────

    def backup(self, label: str = None) -> str:
        """Create a timestamped backup of all entity states.

        Returns the path to the backup file.
        """
        backup_dir = os.path.join(self._state_dir, ".backups")
        os.makedirs(backup_dir, exist_ok=True)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        suffix = f"_{label}" if label else ""
        filename = f"backup_{ts}{suffix}.dlc-state"
        path = os.path.join(backup_dir, filename)

        data = self.export_state()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        return path

    def restore(self, backup_path: str) -> None:
        """Restore state from a .dlc-state backup file.

        Overwrites all current entity states with the backup contents.
        """
        with open(backup_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.import_state(data)

    def list_backups(self) -> list[str]:
        """List available backup files, newest first."""
        backup_dir = os.path.join(self._state_dir, ".backups")
        if not os.path.isdir(backup_dir):
            return []
        files = [f for f in os.listdir(backup_dir) if f.endswith(".dlc-state")]
        files.sort(reverse=True)
        return [os.path.join(backup_dir, f) for f in files]

    # ── Internal ─────────────────────────────────────────────

    def _path(self, entity_id: str) -> str:
        return os.path.join(self._state_dir, f"{entity_id}.json")
