"""Sozlamalar: .env fayli yoki muhit o'zgaruvchilaridan o'qiladi."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def load_dotenv(path: str = ".env") -> None:
    """Oddiy .env o'quvchi (qo'shimcha kutubxonasiz). Mavjud o'zgaruvchilarni bosib yozmaydi."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass
class Config:
    llm_provider: str
    llm_model: str
    telegram_token: str
    telegram_chat_id: str
    youtube_client_secret: str
    youtube_token_file: str
    youtube_category_id: str
    timezone: ZoneInfo
    publish_days: list[int]
    publish_hour: int
    publish_minute: int
    prepare_hours_before: float
    comment_check_minutes: int
    comment_lookback_days: int
    video_language: str
    tts_voice: str
    topics: list[str]
    font_path: str
    font_bold_path: str
    data_dir: Path
    extra: dict = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> "Config":
        load_dotenv()
        hh, mm = _env("PUBLISH_TIME", "19:00").split(":")
        days = [WEEKDAYS[d.strip().lower()[:3]] for d in _env("PUBLISH_DAYS", "mon,tue,thu,sat").split(",") if d.strip()]
        provider = _env("LLM_PROVIDER", "claude").lower()
        data_dir = Path(_env("DATA_DIR", "data"))
        data_dir.mkdir(parents=True, exist_ok=True)
        return cls(
            llm_provider=provider,
            llm_model=_env("OPENAI_MODEL", "gpt-5") if provider == "openai" else _env("CLAUDE_MODEL", "claude-opus-5-5"),
            telegram_token=_env("TELEGRAM_BOT_TOKEN"),
            telegram_chat_id=_env("TELEGRAM_CHAT_ID"),
            youtube_client_secret=_env("YOUTUBE_CLIENT_SECRET", "client_secret.json"),
            youtube_token_file=_env("YOUTUBE_TOKEN_FILE", "token.json"),
            youtube_category_id=_env("YOUTUBE_CATEGORY_ID", "28"),
            timezone=ZoneInfo(_env("TIMEZONE", "Asia/Tashkent")),
            publish_days=sorted(set(days)),
            publish_hour=int(hh),
            publish_minute=int(mm),
            prepare_hours_before=float(_env("PREPARE_HOURS_BEFORE", "3")),
            comment_check_minutes=int(_env("COMMENT_CHECK_MINUTES", "30")),
            comment_lookback_days=int(_env("COMMENT_LOOKBACK_DAYS", "3")),
            video_language=_env("VIDEO_LANGUAGE", "o'zbek"),
            tts_voice=_env("TTS_VOICE", "uz-UZ-SardorNeural"),
            topics=[t.strip() for t in _env("TOPICS", "Tibbiyot,Ilm-fan,Sun'iy intellekt,Qiziqarli faktlar").split(",") if t.strip()],
            font_path=_env("FONT_PATH", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            font_bold_path=_env("FONT_BOLD_PATH", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
            data_dir=data_dir,
        )
