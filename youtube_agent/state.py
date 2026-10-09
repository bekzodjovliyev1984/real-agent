"""Agent holatini JSON faylda saqlash (qayta ishga tushganda yo'qolmasligi uchun)."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

DEFAULT_STATE: dict[str, Any] = {
    "topic_index": 0,
    "published_titles": [],   # takrorlanmaslik uchun oxirgi mavzular
    "prepared_slots": [],     # tayyorlangan jadval vaqtlari (ISO)
    "seen_comments": [],      # ko'rib chiqilgan komment ID'lari
    "pending": {},            # Telegram'da javob kutayotgan so'rovlar
    "awaiting_edit": None,    # tahrir matnini kutayotgan komment so'rovi ID'si
    "last_comment_check": None,
}


class State:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.RLock()
        self.data: dict[str, Any] = json.loads(json.dumps(DEFAULT_STATE))
        if path.exists():
            self.data.update(json.loads(path.read_text(encoding="utf-8")))

    def save(self) -> None:
        with self.lock:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.path)

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        with self.lock:
            self.data[key] = value
            self.save()

    def update_pending(self, pid: str, **fields: Any) -> dict:
        with self.lock:
            self.data["pending"].setdefault(pid, {}).update(fields)
            self.save()
            return self.data["pending"][pid]

    def pop_pending(self, pid: str) -> dict | None:
        with self.lock:
            item = self.data["pending"].pop(pid, None)
            self.save()
            return item

    def mark_comment_seen(self, comment_id: str) -> None:
        with self.lock:
            seen = self.data["seen_comments"]
            if comment_id not in seen:
                seen.append(comment_id)
                del seen[:-5000]  # fayl cheksiz o'smasin
            self.save()
