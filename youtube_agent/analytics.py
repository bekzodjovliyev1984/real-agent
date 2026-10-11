"""M. YouTube statistikasi va o'rganish halqasi (SQLite).

- Har nashr qilingan video bazaga yoziladi: soha, hook turi, ovoz, vizual strategiya, davomiylik, QA hisobot.
- `snapshot` YouTube Analytics API'dan ko'rsatkichlarni oladi va vaqt bilan saqlaydi.
- `summary` sohalar va hook turlari bo'yicha solishtiradi va keyingi tajribalarni taklif qiladi.

Cheklovlar: "viewed vs swiped away" (Shorts feed'da ko'rildi/o'tkazib yuborildi) ko'rsatkichi Analytics API'da
mavjud emas - u faqat YouTube Studio'da ko'rinadi, shuning uchun bazada NULL saqlanadi. Bog'liqlik sabab emas:
taqqoslash faqat yo'nalish uchun.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import closing
from datetime import date, datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

METRICS = ["views", "estimatedMinutesWatched", "averageViewDuration", "averageViewPercentage", "likes",
           "comments", "shares", "subscribersGained"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
    job_id TEXT PRIMARY KEY, video_id TEXT UNIQUE, title TEXT, category TEXT, hook_type TEXT,
    script_template TEXT, tts_provider TEXT, tts_voice TEXT, visual_strategy TEXT, duration REAL,
    published_at TEXT, privacy TEXT, qa_report TEXT, plan_path TEXT
);
CREATE TABLE IF NOT EXISTS metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT, video_id TEXT, captured_at TEXT, days_since_publish INTEGER,
    views INTEGER, watch_minutes REAL, avg_view_duration REAL, avg_view_percentage REAL, likes INTEGER,
    comments INTEGER, shares INTEGER, subscribers_gained INTEGER, viewed_vs_swiped REAL, note TEXT
);
"""


class ChannelDB:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._conn()) as c:
            c.executescript(SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def record_video(self, row: dict) -> None:
        cols = ["job_id", "video_id", "title", "category", "hook_type", "script_template", "tts_provider",
                "tts_voice", "visual_strategy", "duration", "published_at", "privacy", "qa_report", "plan_path"]
        with closing(self._conn()) as c, c:
            c.execute(f"INSERT OR REPLACE INTO videos ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                      [row.get(k) for k in cols])

    def videos(self) -> list[sqlite3.Row]:
        with closing(self._conn()) as c:
            return c.execute("SELECT * FROM videos WHERE video_id IS NOT NULL ORDER BY published_at").fetchall()

    def add_snapshot(self, video_id: str, days: int, m: dict, note: str = "") -> None:
        with closing(self._conn()) as c, c:
            c.execute("""INSERT INTO metrics (video_id, captured_at, days_since_publish, views, watch_minutes,
                         avg_view_duration, avg_view_percentage, likes, comments, shares, subscribers_gained,
                         viewed_vs_swiped, note) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (video_id, datetime.now(timezone.utc).isoformat(timespec="seconds"), days, m.get("views"),
                       m.get("estimatedMinutesWatched"), m.get("averageViewDuration"), m.get("averageViewPercentage"),
                       m.get("likes"), m.get("comments"), m.get("shares"), m.get("subscribersGained"), None, note))

    def latest_metrics(self, max_days: int | None = None) -> list[sqlite3.Row]:
        """Har video uchun oxirgi snapshot (ixtiyoriy: nashrdan keyingi N kun ichida olingan) + video ma'lumotlari."""
        cond = "AND m.days_since_publish <= ?" if max_days else ""
        args = [max_days] if max_days else []
        with closing(self._conn()) as c:
            return c.execute(f"""
                SELECT v.*, m.* FROM videos v JOIN metrics m ON m.video_id = v.video_id
                WHERE m.id = (SELECT id FROM metrics m2 WHERE m2.video_id = v.video_id {cond.replace('m.', 'm2.')}
                              ORDER BY captured_at DESC LIMIT 1)""", args).fetchall()


def fetch_video_metrics(creds, video_id: str, published_at: str) -> dict:
    """YouTube Analytics API v2 (reports.query). Ma'lumot bo'lmasa - qiymatlar None."""
    from googleapiclient.discovery import build

    api = build("youtubeAnalytics", "v2", credentials=creds, cache_discovery=False)
    start = (published_at or date.today().isoformat())[:10]
    res = api.reports().query(ids="channel==MINE", startDate=start, endDate=date.today().isoformat(),
                              metrics=",".join(METRICS), filters=f"video=={video_id}").execute()
    rows = res.get("rows") or []
    if not rows:
        return {k: None for k in METRICS}
    headers = [h["name"] for h in res.get("columnHeaders", [])]
    return dict(zip(headers, rows[0]))


def snapshot_all(db: ChannelDB, creds) -> int:
    n = 0
    for v in db.videos():
        try:
            m = fetch_video_metrics(creds, v["video_id"], v["published_at"])
        except Exception as e:
            log.warning("Statistika olinmadi %s: %s", v["video_id"], e)
            continue
        days = (date.today() - date.fromisoformat((v["published_at"] or date.today().isoformat())[:10])).days
        db.add_snapshot(v["video_id"], days, m, note="viewed_vs_swiped: Analytics API'da mavjud emas")
        n += 1
    return n


def summary(db: ChannelDB, window_days: int = 7) -> str:
    """Sohalar va hook turlari bo'yicha qisqa taqqoslash (bir xil vaqt oynasida) + tajriba takliflari."""
    rows = db.latest_metrics(window_days)
    if not rows:
        return ""
    def agg(key: str) -> list[tuple[str, int, float | None, float | None]]:
        groups: dict[str, list] = {}
        for r in rows:
            groups.setdefault(r[key] or "?", []).append(r)
        out = []
        for k, rs in groups.items():
            pct = [r["avg_view_percentage"] for r in rs if r["avg_view_percentage"] is not None]
            views = [r["views"] for r in rs if r["views"] is not None]
            out.append((k, len(rs), round(sum(pct) / len(pct), 1) if pct else None,
                        round(sum(views) / len(views)) if views else None))
        return sorted(out, key=lambda x: -(x[2] or 0))

    lines = [f"Oxirgi {window_days} kunlik oynada {len(rows)} video:"]
    for key, title in (("category", "Soha"), ("hook_type", "Hook")):
        for name, n, pct, views in agg(key):
            lines.append(f"- {title} «{name}»: {n} ta video, o'rtacha ko'rilgan qism {pct}%, o'rtacha {views} ko'rish")
    small = [name for name, n, _, _ in agg("hook_type") if n < 3]
    if small:
        lines.append(f"Tajriba: bu hook turlari bo'yicha ma'lumot kam ({', '.join(small)}) - ko'proq sinab ko'rish kerak.")
    lines.append("Eslatma: bu bog'liqlik, sabab emas; namunalar kichik.")
    return "\n".join(lines)


def record_publication(db: ChannelDB, job, video_id: str, privacy: str) -> None:
    plan = job.read_json("plan.json")
    assets = job.read_json("assets.json") if job.has("assets.json") else []
    nar = job.read_json("narration.json") if job.has("narration.json") else {}
    kinds = [a["media_type"] for a in assets]
    db.record_video({
        "job_id": job.id, "video_id": video_id, "title": plan["title"], "category": plan["category"],
        "hook_type": plan.get("hook_type"), "script_template": "hook-setup-development-payoff",
        "tts_provider": nar.get("provider"), "tts_voice": nar.get("voice"),
        "visual_strategy": json.dumps({k: kinds.count(k) for k in set(kinds)}), "duration": nar.get("duration"),
        "published_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "privacy": privacy,
        "qa_report": job.path("qa_report.json").read_text("utf-8") if job.has("qa_report.json") else None,
        "plan_path": str(job.path("plan.json")),
    })
