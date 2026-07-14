"""DLC Memory — TimelineStore: dual-core linear memory (core 2).

Single-file JSONL timeline with hourly granularity.
Same-hour writes overwrite the previous entry for that hour slot.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime


class TimelineStore:
    """Time-aware memory — one entry per hour slot.

    File layout:
        <root_dir>/timeline.jsonl

    Each line:
        {"date_hour": "2026-07-09-14", "ts": 1752050000.0, "summary": "...", ...}

    Same-hour write: if date_hour already exists, overwrite that line.
    """

    def __init__(self, root_dir: str):
        self.root_dir = os.path.abspath(root_dir)
        os.makedirs(self.root_dir, exist_ok=True)

    @property
    def _file(self) -> str:
        return os.path.join(self.root_dir, "timeline.jsonl")

    @property
    def _lock_file(self) -> str:
        return os.path.join(self.root_dir, "timeline.jsonl.lock")

    # ── locking ──────────────────────────────────────────────

    def _acquire_lock(self, timeout: float = 5.0) -> bool:
        """Advisory file lock — wait up to timeout seconds."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                fd = os.open(self._lock_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.close(fd)
                return True
            except FileExistsError:
                time.sleep(0.05)
        return False

    def _release_lock(self):
        try:
            os.unlink(self._lock_file)
        except FileNotFoundError:
            pass

    # ── read ────────────────────────────────────────────────

    def _load_all(self) -> list[dict]:
        """Load all entries as list of dicts."""
        if not os.path.isfile(self._file):
            return []
        entries = []
        with open(self._file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return entries

    def list_all(self) -> list:
        """Return all timeline entries, sorted by timestamp."""
        entries = self._load_all()
        entries.sort(key=lambda e: e.get("ts", 0))
        return entries

    def get_hour(self, date_hour: str) -> dict | None:
        """Get entry for a specific hour slot."""
        for e in self._load_all():
            if e.get("date_hour") == date_hour:
                return e
        return None

    def recent(self, n: int = 24):
        """Return most recent N entries."""
        entries = self.list_all()
        return entries[-n:]

    # ── write (same-hour overwrite) ─────────────────────────

    def write(self, date_hour: str, **data) -> str:
        """Write or overwrite an hourly entry.

        Args:
            date_hour: "YYYY-MM-DD-HH" format
            **data: fields to store (summary, mood, events, ...)

        Returns:
            date_hour that was written
        """
        if not self._acquire_lock():
            raise RuntimeError("TimelineStore: lock timeout")

        try:
            entries = self._load_all()

            # Check if this hour already exists → overwrite
            found = False
            now = time.time()
            for e in entries:
                if e.get("date_hour") == date_hour:
                    e["ts"] = now
                    e.update(data)
                    found = True
                    break

            if not found:
                entries.append({"date_hour": date_hour, "ts": now, **data})

            self._save(entries)
            return date_hour

        finally:
            self._release_lock()

    def _save(self, entries: list[dict]):
        """Atomic write to timeline.jsonl."""
        tmp = self._file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self._file)

    # ── search ──────────────────────────────────────────────

    def search(self, keyword: str, max_results: int = 20) -> list[dict]:
        """Keyword search across all timeline entries."""
        results = []
        kw = keyword.lower()
        for e in self.list_all():
            if kw in json.dumps(e, ensure_ascii=False).lower():
                results.append(e)
                if len(results) >= max_results:
                    break
        return results

    # ── format ──────────────────────────────────────────────

    def format_context(self, entries: list[dict], max_entries: int = 24) -> str:
        """Format timeline entries for LLM context injection."""
        if not entries:
            return ""
        lines = []
        for e in entries[-max_entries:]:
            dh = e.get("date_hour", "???")
            summary = e.get("summary", e.get("content", ""))[:100]
            lines.append(f"[{dh}] {summary}")
        return "\n".join(lines)

    # ── stats ───────────────────────────────────────────────

    def stats(self) -> dict:
        """Return timeline stats."""
        entries = self.list_all()
        return {
            "total_hours": len(entries),
            "span_start": entries[0]["date_hour"] if entries else None,
            "span_end": entries[-1]["date_hour"] if entries else None,
        }

    # ── range query ─────────────────────────────────────────

    def range(self, start_hour: str, end_hour: str) -> list[dict]:
        """Return entries whose date_hour is in [start_hour, end_hour]."""
        entries = self.list_all()
        return [e for e in entries
                if start_hour <= e.get("date_hour", "") <= end_hour]
