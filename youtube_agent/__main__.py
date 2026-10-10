"""Ishga tushirish:
    python -m youtube_agent auth      # bir martalik YouTube ruxsati
    python -m youtube_agent run       # agentni doimiy ishga tushirish
    python -m youtube_agent test-video  # Telegram/YouTube'siz bitta video yasab ko'rish
"""

import logging
import sys

from .config import Config


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
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
