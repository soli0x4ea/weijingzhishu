"""DLC Memory — Unified search over ChatlogStore + TimelineStore."""
from __future__ import annotations

from datetime import datetime

from dlc.memory.chatlog import ChatlogStore
from dlc.memory.timeline import TimelineStore


class MemorySearch:
    """Unified search interface over dual-core linear memory."""

    def __init__(self, chatlog: ChatlogStore, timeline: TimelineStore):
        self.chatlog = chatlog
        self.timeline = timeline

    # ── date queries ────────────────────────────────────────

    def by_date(self, date_str: str) -> dict:
        """Get all memory for a specific date: chatlog entries + full-day timeline."""
        return {
            "chatlog": self.chatlog.load_day(date_str),
            "timeline": self.timeline.range(date_str + "-00", date_str + "-23"),
        }

    def by_range(self, start: str, end: str) -> dict:
        """Get memory in date range."""
        return {
            "chatlog": self.chatlog.load_range(start, end),
            "timeline": self.timeline.range(start + "-00", end + "-23"),
        }

    # ── recent ──────────────────────────────────────────────

    def recent(self, n_chatlog: int = 10, n_timeline: int = 24) -> dict:
        """Get most recent entries from both stores."""
        return {
            "chatlog": self.chatlog.recent(n_chatlog),
            "timeline": self.timeline.recent(n_timeline),
        }

    # ── keyword search ──────────────────────────────────────

    def search(self, keyword: str, max_results: int = 30) -> dict:
        """Search across all memory by keyword."""
        return {
            "chatlog": self.chatlog.search(keyword, max_results=max_results),
            "timeline": self.timeline.search(keyword, max_results=max_results),
        }

    # ── stats ───────────────────────────────────────────────

    def stats(self) -> dict:
        """Aggregate stats across both stores."""
        return {
            "chatlog": self.chatlog.stats(),
            "timeline": self.timeline.stats(),
        }

    # ── context injection ───────────────────────────────────

    def inject_context(self, chatlog_days: int = 3, max_chatlog: int = 15,
                       max_timeline: int = 24) -> str:
        """Generate LLM context from both memory stores."""
        parts = []

        # Timeline first (time awareness)
        tl_entries = self.timeline.recent(max_timeline)
        if tl_entries:
            parts.append("[时间线]")
            for e in tl_entries:
                dh = e.get("date_hour", "???")
                summary = e.get("summary", e.get("content", ""))[:80]
                parts.append(f"  {dh}  {summary}")

        # Chatlog — recent days
        start_date = datetime.fromtimestamp(
            __import__("time").time() - chatlog_days * 86400
        ).strftime("%Y-%m-%d")
        end_date = datetime.now().strftime("%Y-%m-%d")
        cl_entries = self.chatlog.load_range(start_date, end_date)
        if cl_entries:
            parts.append(f"\n[对话记忆 — 最近{chatlog_days}天]")
            for e in cl_entries[-max_chatlog:]:
                ts = e.get("ts", 0)
                dt = datetime.fromtimestamp(ts).strftime("%m-%d %H:%M") if ts else "???"
                role = e.get("role", "?")
                content = e.get("content", "")[:100]
                parts.append(f"  [{dt}][{role}] {content}")

        return "\n".join(parts) if len(parts) > 1 else ""
