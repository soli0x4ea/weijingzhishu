"""DLC Memory — Import tool: migrate from Soli legacy format.

Reads Soli's MEMORY/chatlog/*.jsonl format and imports into
DLC's ChatlogStore + TimelineStore using efficient batch operations.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime

from dlc.memory.chatlog import ChatlogStore
from dlc.memory.timeline import TimelineStore


def _parse_ts(ts_val):
    """Parse Soli's ISO-format timestamp to Unix float.

    Supports: "2026-05-10T23:00:11.792000+08:00" and unix float.
    """
    if isinstance(ts_val, (int, float)):
        return float(ts_val)
    if isinstance(ts_val, str):
        # Try ISO format
        try:
            from datetime import timezone, timedelta
            # Parse "2026-05-10T23:00:11.792000+08:00"
            m = re.match(
                r'(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})\.?(\d*)([+-]\d{2}:\d{2})?',
                ts_val
            )
            if m:
                date_part, time_part, micro_part, tz_part = m.groups()
                dt_str = f"{date_part}T{time_part}"
                if micro_part:
                    dt_str += f".{micro_part[:6].ljust(6, '0')}"
                if tz_part:
                    dt_str += tz_part
                else:
                    dt_str += "+08:00"
                dt = datetime.fromisoformat(dt_str)
                return dt.timestamp()
        except Exception:
            pass
    return 0.0


def import_chatlog(soli_chatlog_dir: str, dlc_chatlog: ChatlogStore) -> dict:
    """Import all .jsonl files from Soli's MEMORY/chatlog/ into DLC ChatlogStore.

    Soli format per line:
        {"ts": "2026-05-10T23:00:11+08:00", "role": "user", "content": "..."}
        {"ts": 1752050000.0, "hash": "...", "role": "user", "content": "..."}

    Uses batch_append for efficiency — one atomic write per day.

    Returns:
        {"imported": N, "skipped": N, "files": N}
    """
    imported = 0
    skipped = 0
    file_count = 0

    if not os.path.isdir(soli_chatlog_dir):
        return {"imported": 0, "skipped": 0, "files": 0, "error": "source not found"}

    for fname in sorted(os.listdir(soli_chatlog_dir)):
        if not fname.endswith(".jsonl"):
            continue
        fpath = os.path.join(soli_chatlog_dir, fname)
        file_count += 1

        # Extract date from filename (e.g. "2026-05-10.jsonl")
        date_str = fname.replace(".jsonl", "")

        # Read all entries from this day
        day_entries = []
        with open(fpath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                role = entry.get("role", "unknown")
                content = entry.get("content", "")
                if not content:
                    continue

                ts = _parse_ts(entry.get("ts", 0))

                day_entries.append({
                    "role": role,
                    "content": content,
                    "ts": ts,
                })

        if day_entries:
            result = dlc_chatlog.batch_append(date_str, day_entries)
            imported += result.get("added", 0)
            skipped += result.get("skipped", 0)

    return {"imported": imported, "skipped": skipped, "files": file_count}


def import_timeline(soli_timeline: str, dlc_timeline: TimelineStore) -> dict:
    """Import Soli's time_river data into DLC TimelineStore.

    Soli format: dict of {hour_slot: {summary: ..., ...}}

    Returns:
        {"imported": N, "skipped": N}
    """
    imported = 0

    if isinstance(soli_timeline, str):
        if not os.path.isfile(soli_timeline):
            return {"imported": 0, "skipped": 0, "error": f"not found: {soli_timeline}"}
        with open(soli_timeline, "r", encoding="utf-8") as f:
            data = json.load(f)
    elif isinstance(soli_timeline, dict):
        data = soli_timeline
    else:
        return {"imported": 0, "skipped": 0, "error": "unsupported type"}

    for hour_slot, entry in data.items():
        if not isinstance(entry, dict):
            continue
        dlc_timeline.write(hour_slot, **entry)
        imported += 1

    return {"imported": imported, "skipped": 0}
