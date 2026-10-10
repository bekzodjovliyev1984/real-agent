"""Ishga tushirish:
    python -m youtube_agent auth      # bir martalik YouTube ruxsati
    python -m youtube_agent run       # agentni doimiy ishga tushirish
    python -m youtube_agent test-video  # Telegram/YouTube'siz bitta video yasab ko'rish
    python -m youtube_agent set-key PIXABAY_API_KEY  # .env ga kalit yozish (Bloknotsiz)
"""

import logging
import sys
from pathlib import Path

from .config import Config


def set_key(name: str, env_path: Path = Path(".env")) -> None:
    """Kalitni so'rab, .env faylida shu nomli qatorni yangilaydi yoki oxiriga qo'shadi."""
    value = input(f"{name} qiymatini qo'ying (sichqonchaning o'ng tugmasi) va Enter bosing: ").strip()
    if not value:
        sys.exit("Hech narsa kiritilmadi, .env o'zgarmadi.")
    lines = env_path.read_text(encoding="utf-8-sig").splitlines() if env_path.exists() else []
    for i, line in enumerate(lines):
        if line.split("=", 1)[0].strip() == name:
            lines[i] = f"{name}={value}"
            break
    else:
        lines.append(f"{name}={value}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"✅ {name} .env fayliga yozildi.")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "set-key":
        if len(sys.argv) < 3:
            sys.exit("Masalan: python -m youtube_agent set-key PIXABAY_API_KEY")
        return set_key(sys.argv[2].upper())
    cfg = Config.from_env()
    if cmd == "auth":
        from .youtube import authorize
        authorize(cfg.youtube_client_secret, cfg.youtube_token_file)
    elif cmd == "test-video":
        from .content import make_creator
        from .video import VideoMaker
        category = sys.argv[2] if len(sys.argv) > 2 else cfg.topics[0]
        plan = make_creator(cfg.llm_provider, cfg.llm_model, cfg.video_language).create_video_plan(category, [])
        video, thumb = VideoMaker(cfg.shorts_settings()).build(
            plan, category, cfg.data_dir / "videos" / "test")
        print(f"Sarlavha: {plan.title}\nVideo: {video}\nMuqova: {thumb}")
    elif cmd == "run":
        if not cfg.telegram_token:
            sys.exit("TELEGRAM_BOT_TOKEN .env faylida ko'rsatilmagan")
        from .agent import Agent
        Agent(cfg).run()
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
