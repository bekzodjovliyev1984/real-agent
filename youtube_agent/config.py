"""Sozlamalar: .env fayli yoki muhit o'zgaruvchilaridan o'qiladi. Kalitlar kodda saqlanmaydi."""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
DEFAULT_TOPICS = "Sun'iy intellekt,Yangi texnologiyalar,Yangi mashinalar,Ilm-fan,Ta'lim"


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
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].strip()  # qator oxiridagi izoh
        if value:  # bo'sh kalitlar muhitga yozilmaydi (SDK'lar bo'sh kalitni xato deb biladi)
            os.environ.setdefault(key.strip(), value)


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


def _flag(name: str, default: str = "0") -> bool:
    return _env(name, default).lower() in ("1", "true", "yes", "ha")


def _float(name: str, default: float) -> float:
    return float(_env(name, str(default)))


@dataclass
class Config:
    # sun'iy intellekt
    llm_provider: str
    llm_model: str
    llm_cheap_model: str
    # ovoz
    tts_provider: str
    tts_voice: str
    tts_model: str
    tts_instructions: str
    tts_rate: str
    tts_price_per_min: float
    use_asr: bool
    # vizual
    pexels_key: str
    pixabay_key: str
    allow_publisher_images: bool
    vision_check: bool
    visual_min_score: float
    ai_video_provider: str
    ai_video_model: str
    ai_video_price_per_sec: float
    # audio
    music_dir: Path
    music_db: float
    sfx_dir: Path
    target_lufs: float
    # davomiylik va sifat
    min_seconds: float
    max_seconds: float
    max_corrections: int
    qa_min: dict[str, float]
    # telegram / youtube / jadval
    telegram_token: str
    telegram_chat_id: str
    youtube_client_secret: str
    youtube_token_file: str
    youtube_category_id: str
    youtube_privacy: str
    timezone: ZoneInfo
    publish_days: list[int]
    publish_hour: int
    publish_minute: int
    prepare_hours_before: float
    comment_check_minutes: int
    comment_lookback_days: int
    topics: list[str]
    # fayllar
    font_path: str
    font_bold_path: str
    headline_font_path: str
    data_dir: Path
    jobs_dir: Path
    db_path: Path
    pronunciation_path: Path
    extra: dict = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> "Config":
        load_dotenv()
        hh, mm = _env("PUBLISH_TIME", "19:00").split(":")
        days = [WEEKDAYS[d.strip().lower()[:3]] for d in _env("PUBLISH_DAYS", "mon,tue,thu,sat").split(",") if d.strip()]
        provider = _env("LLM_PROVIDER", "openai").lower()
        tts_provider = _env("TTS_PROVIDER", "openai").lower()
        if tts_provider == "openai":
            voice = _env("OPENAI_TTS_VOICE", "marin")
        else:
            voice = _env("EDGE_TTS_VOICE", _env("TTS_VOICE", "uz-UZ-SardorNeural"))
        data_dir = Path(_env("DATA_DIR", "data"))
        data_dir.mkdir(parents=True, exist_ok=True)
        return cls(
            llm_provider=provider,
            llm_model=_env("OPENAI_MODEL", "gpt-5") if provider == "openai" else _env("CLAUDE_MODEL", "claude-opus-5-5"),
            llm_cheap_model=(_env("OPENAI_CHEAP_MODEL", "gpt-5-mini") if provider == "openai"
                             else _env("CLAUDE_CHEAP_MODEL", "claude-haiku-5-5")),
            tts_provider=tts_provider,
            tts_voice=voice,
            tts_model=_env("TTS_MODEL", "gpt-4o-mini-tts"),
            tts_instructions=_env("TTS_INSTRUCTIONS"),
            tts_rate=_env("TTS_RATE", "+0%"),
            tts_price_per_min=_float("PRICE_TTS_PER_MIN", 0.015),
            use_asr=_flag("USE_ASR", "1") and bool(_env("OPENAI_API_KEY")),
            pexels_key=_env("PEXELS_API_KEY"),
            pixabay_key=_env("PIXABAY_API_KEY"),
            allow_publisher_images=_flag("ALLOW_PUBLISHER_IMAGES", "1"),
            vision_check=_flag("VISION_CHECK", "1"),
            visual_min_score=_float("VISUAL_MIN_SCORE", 6.0),
            ai_video_provider=_env("AI_VIDEO_PROVIDER", "none").lower(),
            ai_video_model=_env("AI_VIDEO_MODEL", "sora-2"),
            ai_video_price_per_sec=_float("PRICE_SORA_PER_SEC", 0.10),
            music_dir=Path(_env("MUSIC_DIR", "music")),
            music_db=_float("MUSIC_DB", -22.0),
            sfx_dir=Path(_env("SFX_DIR", "sfx")),
            target_lufs=_float("TARGET_LUFS", -14.0),
            min_seconds=_float("SHORT_MIN_SECONDS", 25.0),
            max_seconds=_float("SHORT_MAX_SECONDS", 55.0),
            max_corrections=int(_env("MAX_CORRECTIONS", "2")),
            qa_min={"storytelling": _float("QA_MIN_STORY", 6), "visual_relevance": _float("QA_MIN_VISUAL", 7),
                    "audio_quality": _float("QA_MIN_AUDIO", 7), "subtitle_quality": _float("QA_MIN_SUBTITLE", 6),
                    "technical_quality": _float("QA_MIN_TECHNICAL", 7)},
            telegram_token=_env("TELEGRAM_BOT_TOKEN"),
            telegram_chat_id=_env("TELEGRAM_CHAT_ID"),
            youtube_client_secret=_env("YOUTUBE_CLIENT_SECRET", "client_secret.json"),
            youtube_token_file=_env("YOUTUBE_TOKEN_FILE", "token.json"),
            youtube_category_id=_env("YOUTUBE_CATEGORY_ID", "28"),
            youtube_privacy=_env("YOUTUBE_PRIVACY", "private").lower(),
            timezone=ZoneInfo(_env("TIMEZONE", "Asia/Tashkent")),
            publish_days=sorted(set(days)),
            publish_hour=int(hh),
            publish_minute=int(mm),
            prepare_hours_before=_float("PREPARE_HOURS_BEFORE", 3),
            comment_check_minutes=int(_env("COMMENT_CHECK_MINUTES", "30")),
            comment_lookback_days=int(_env("COMMENT_LOOKBACK_DAYS", "3")),
            topics=[t.strip() for t in _env("TOPICS", DEFAULT_TOPICS).split(",") if t.strip()],
            font_path=_env("FONT_PATH", DEFAULT_FONT),
            font_bold_path=_env("FONT_BOLD_PATH", DEFAULT_FONT_BOLD),
            headline_font_path=_env("HEADLINE_FONT_PATH", DEFAULT_HEADLINE_FONT),
            data_dir=data_dir,
            jobs_dir=Path(_env("JOBS_DIR", str(data_dir / "jobs"))),
            db_path=Path(_env("DB_PATH", str(data_dir / "channel.db"))),
            pronunciation_path=Path(_env("PRONUNCIATION_FILE", str(data_dir / "pronunciation.json"))),
        )
