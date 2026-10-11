"""Sozlamalar: .env fayli yoki muhit o'zgaruvchilaridan o'qiladi."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def load_dotenv(path: str = ".env") -> None:
    """Oddiy .env o'quvchi (qo'shimcha kutubxonasiz). Mavjud o'zgaruvchilarni bosib yozmaydi."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


if sys.platform == "win32":
    DEFAULT_FONT, DEFAULT_FONT_BOLD = r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\arialbd.ttf"
    DEFAULT_HEADLINE_FONT = r"C:\Windows\Fonts\impact.ttf"
elif sys.platform == "darwin":
    DEFAULT_FONT = DEFAULT_FONT_BOLD = "/System/Library/Fonts/Supplemental/Arial.ttf"
    DEFAULT_HEADLINE_FONT = "/System/Library/Fonts/Supplemental/Impact.ttf"
else:
    DEFAULT_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    DEFAULT_FONT_BOLD = DEFAULT_HEADLINE_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _flag(name: str) -> bool:
    return _env(name, "0").lower() in ("1", "true", "yes", "ha")


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
    tts_rate: str
    pixabay_key: str
    music_dir: str
    ai_images: bool
    stock_fallback: bool
    font_path: str
    font_bold_path: str
    headline_font_path: str
    data_dir: Path
    extra: dict = field(default_factory=dict)

    def shorts_settings(self):
        from .video import ShortsSettings

        return ShortsSettings(self.tts_voice, self.tts_rate, self.font_path, self.font_bold_path,
                              self.headline_font_path, self.pixabay_key, self.music_dir, self.ai_images,
                              self.stock_fallback)

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
            topics=[t.strip() for t in _env("TOPICS", "Koinot,Sun'iy intellekt,Tibbiyot,Ilm-fan").split(",") if t.strip()],
            tts_rate=_env("TTS_RATE", "+8%"),
            pixabay_key=_env("PIXABAY_API_KEY"),
            music_dir=_env("MUSIC_DIR", "music"),
            ai_images=_flag("AI_IMAGES"),
            stock_fallback=_flag("STOCK_FALLBACK"),
            font_path=_env("FONT_PATH", DEFAULT_FONT),
            font_bold_path=_env("FONT_BOLD_PATH", DEFAULT_FONT_BOLD),
            headline_font_path=_env("HEADLINE_FONT_PATH", DEFAULT_HEADLINE_FONT),
            data_dir=data_dir,
        )
