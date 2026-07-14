"""DLC Memory — ChatlogStore: dual-core linear memory (core 1).

JSONL-based chatlog store with daily partitioning, atomic writes,
MD5 deduplication, and file locking.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime


class ChatlogStore:
    """JSONL-based chatlog — linear conversation memory.

    Directory layout:
        <root_dir>/YYYY-MM-DD.jsonl

    Each line is a JSON object with:
        ts: float         — unix timestamp
        hash: str         — MD5 hex digest
        role: str         — "user", "assistant", "memory", "summary", ...
        content: str      — the actual text
        ...               — any extra fields passed as **meta

    Atomic write: write to .tmp file → flush → rename to .jsonl
    Dedup: MD5 of (role + content) → skip if hash already exists
    File lock: advisory .lock file with 5s timeout
    """

    def __init__(self, root_dir: str):
        self.root_dir = os.path.abspath(root_dir)
        os.makedirs(self.root_dir, exist_ok=True)

    # ── file paths ──────────────────────────────────────────

    def _day_file(self, date_str: str) -> str:
        return os.path.join(self.root_dir, f"{date_str}.jsonl")

    def _tmp_file(self, date_str: str) -> str:
        return os.path.join(self.root_dir, f"{date_str}.jsonl.tmp")

    def _lock_file(self, date_str: str) -> str:
        return os.path.join(self.root_dir, f"{date_str}.jsonl.lock")

    # ── helpers ─────────────────────────────────────────────

    def _hash(self, role: str, content: str) -> str:
        return hashlib.md5(f"{role}|{content}".encode("utf-8")).hexdigest()

    def _acquire_lock(self, date_str: str, timeout: float = 5.0) -> bool:
        """Advisory file lock — wait up to timeout seconds."""
        lf = self._lock_file(date_str)
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                fd = os.open(lf, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.close(fd)
                return True
            except FileExistsError:
                time.sleep(0.05)
        return False

    def _release_lock(self, date_str: str):
        lf = self._lock_file(date_str)
        try:
            os.unlink(lf)
        except FileNotFoundError:
            pass

    def _load_hashes(self, date_str: str) -> set:
        """Load all existing hashes for a day to enable dedup."""
        hashes = set()
        fpath = self._day_file(date_str)
        if not os.path.isfile(fpath):
            return hashes
        with open(fpath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if "hash" in entry:
                        hashes.add(entry["hash"])
                except json.JSONDecodeError:
                    continue
        return hashes

    # ── batch write (for imports) ──────────────────────────

    def batch_append(self, date_str: str, entries: list[dict]) -> dict:
        """Append many entries for a specific date in one atomic write.

        Args:
            date_str: "YYYY-MM-DD"
            entries: list of {role:, content:, **meta} dicts

        Returns:
            {"added": N, "skipped": N}
        """
        if not entries:
            return {"added": 0, "skipped": 0}

        if not self._acquire_lock(date_str, timeout=10.0):
            return {"added": 0, "skipped": 0, "error": "lock timeout"}

        try:
            existing_hashes = self._load_hashes(date_str)
            new_lines = []
            added = 0
            skipped = 0
            now = time.time()

            for entry in entries:
                role = entry.get("role", "unknown")
                content = entry.get("content", "")
                if not content:
                    continue

                h = self._hash(role, content)
                if h in existing_hashes:
                    skipped += 1
                    continue

                line = {
                    "ts": entry.get("ts", now),
                    "hash": h,
                    "role": role,
                    "content": content,
                }
                # Preserve extra fields
                for k, v in entry.items():
                    if k not in ("ts", "hash", "role", "content"):
                        line[k] = v

                new_lines.append(json.dumps(line, ensure_ascii=False))
                existing_hashes.add(h)
                added += 1

            if added == 0:
                return {"added": 0, "skipped": skipped}

            tmp = self._tmp_file(date_str)
            dst = self._day_file(date_str)

            with open(tmp, "w", encoding="utf-8") as f:
                # Copy existing content
                if os.path.isfile(dst):
                    with open(dst, "r", encoding="utf-8") as src:
                        f.write(src.read())
                # Write new entries
                for line in new_lines:
                    f.write(line + "\n")
                f.flush()
                os.fsync(f.fileno())

            os.replace(tmp, dst)
            return {"added": added, "skipped": skipped}

        finally:
            self._release_lock(date_str)

    # ── write ───────────────────────────────────────────────

    def append(self, role: str, content: str, **meta) -> tuple[bool, str]:
        """Append an entry to today's chatlog.

        Args:
            role: entry role (user/assistant/memory/summary/...)
            content: the text content
            **meta: extra fields to store (tags, importance, ...)

        Returns:
            (ok, hash) — True if written, False if duplicate
        """
        date_str = datetime.now().strftime("%Y-%m-%d")
        entry_hash = self._hash(role, content)

        if not self._acquire_lock(date_str):
            return False, entry_hash

        try:
            # Check dedup
            existing = self._load_hashes(date_str)
            if entry_hash in existing:
                return False, entry_hash

            entry = {
                "ts": time.time(),
                "hash": entry_hash,
                "role": role,
                "content": content,
            }
            entry.update(meta)

            entry_line = json.dumps(entry, ensure_ascii=False) + "\n"

            # True append-only — JSONL's core advantage
            dst = self._day_file(date_str)
            with open(dst, "a", encoding="utf-8") as f:
                f.write(entry_line)
                f.flush()
                os.fsync(f.fileno())

            return True, entry_hash

        finally:
            self._release_lock(date_str)

    # ── read ────────────────────────────────────────────────

    def load_day(self, date_str: str) -> list[dict]:
        """Load all entries for a specific day."""
        fpath = self._day_file(date_str)
        if not os.path.isfile(fpath):
            return []
        entries = []
        with open(fpath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return entries

    def load_range(self, start: str, end: str) -> list[dict]:
        """Load entries in date range [start, end] (inclusive)."""
        entries = []
        from datetime import date, timedelta

        s = date.fromisoformat(start)
        e = date.fromisoformat(end)
        current = s
        while current <= e:
            day_entries = self.load_day(current.isoformat())
            entries.extend(day_entries)
            current += timedelta(days=1)
        return entries

    def recent(self, n: int = 10) -> list[dict]:
        """Load most recent N entries across all days."""
        days = sorted(os.listdir(self.root_dir))
        entries = []
        for day_file in reversed(days):
            if not day_file.endswith(".jsonl"):
                continue
            date_str = day_file.replace(".jsonl", "")
            day_entries = self.load_day(date_str)
            entries = day_entries + entries
            if len(entries) >= n:
                break
        return entries[-n:]

    def count_day(self, date_str: str = None) -> int:
        """Count entries. If date_str is None, count today."""
        if date_str is None:
            date_str = datetime.now().strftime("%Y-%m-%d")
        return len(self.load_day(date_str))

    def stats(self) -> dict:
        """Return aggregate stats: total entries, daily breakdown."""
        total = 0
        daily = {}
        for fname in sorted(os.listdir(self.root_dir)):
            if not fname.endswith(".jsonl"):
                continue
            date_str = fname.replace(".jsonl", "")
            n = self.count_day(date_str)
            daily[date_str] = n
            total += n
        return {"total": total, "daily": daily}

    # ── search ──────────────────────────────────────────────

    def search(self, keyword: str, start: str = None, end: str = None,
               max_results: int = 50) -> list[dict]:
        """Simple keyword search (case-insensitive substring match)."""
        results = []
        if start and end:
            entries = self.load_range(start, end)
        elif start:
            entries = self.load_range(start, datetime.now().strftime("%Y-%m-%d"))
        elif end:
            # Scan all days up to end
            days = sorted(os.listdir(self.root_dir))
            entries = []
            for fname in days:
                if not fname.endswith(".jsonl"):
                    continue
                d = fname.replace(".jsonl", "")
                if d <= end:
                    entries.extend(self.load_day(d))
        else:
            # Scan all
            days = sorted(os.listdir(self.root_dir))
            entries = []
            for fname in days:
                if fname.endswith(".jsonl"):
                    entries.extend(self.load_day(fname.replace(".jsonl", "")))

        kw = keyword.lower()
        for e in entries:
            if kw in e.get("content", "").lower():
                results.append(e)
                if len(results) >= max_results:
                    break
        return results

    # ── format ──────────────────────────────────────────────

    # ── latest entry lookup ─────────────────────────────────

    def get_latest(self) -> dict | None:
        """Return the most recent entry across all days, or None if empty."""
        days = sorted(os.listdir(self.root_dir))
        for day_file in reversed(days):
            if not day_file.endswith(".jsonl"):
                continue
            entries = self.load_day(day_file.replace(".jsonl", ""))
            if entries:
                return entries[-1]
        return None

    # ── format ──────────────────────────────────────────────

    def format_context(self, entries: list[dict], max_entries: int = 15) -> str:
        """Format entries for LLM context injection."""
        if not entries:
            return ""
        lines = []
        for e in entries[-max_entries:]:
            ts = e.get("ts", 0)
            if ts:
                dt = datetime.fromtimestamp(ts).strftime("%m-%d %H:%M")
            else:
                dt = "???"
            role = e.get("role", "?")
            content = e.get("content", "")[:120]
            lines.append(f"[{dt}][{role}] {content}")
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# v2.5.3: record_chat — standard chatlog + timeline write entry
# ═══════════════════════════════════════════════════════════════

def record_chat(
    chatlog_store: "ChatlogStore",
    timeline_store: "TimelineStore",
    user_id: str,
    user_message: str,
    assistant_id: str,
    assistant_message: str,
) -> None:
    """Record a complete chat turn — user input + assistant reply.

    This is the single entry point for memory writes. Call it after
    the LLM has generated a response. Timeline is auto-synced.

    Engine (dispatcher, modifier, narrator) does NOT write to memory.
    Memory is produced by the agent layer, consumed by the engine
    (data_loading, memory_search).

    Args:
        chatlog_store: ChatlogStore instance
        timeline_store: TimelineStore instance
        user_id: user identifier ("default", "soli", etc.)
        user_message: raw user input
        assistant_id: assistant identifier (card_id, "soli", etc.)
        assistant_message: LLM-generated response (not engine stdout)
    """
    # 1. Write both sides of the conversation
    chatlog_store.append(user_id, user_message)
    chatlog_store.append(assistant_id, assistant_message)

    # 2. Sync timeline — one entry per chat turn
    from datetime import datetime
    hour = datetime.now().strftime("%Y-%m-%d-%H")
    # Use first 60 chars of user message as summary context
    summary = user_message[:60]
    timeline_store.write(hour, summary=f"对话: {summary}")
