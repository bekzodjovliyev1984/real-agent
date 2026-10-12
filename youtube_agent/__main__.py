"""Buyruqlar:
    python -m youtube_agent produce ["Sun'iy intellekt"]   # bitta Shorts yasash (YouTube'ga YUKLAMAYDI)
    python -m youtube_agent resume <job_id>                 # to'xtab qolgan ishni davom ettirish
    python -m youtube_agent jobs                            # ishlar ro'yxati va holati
    python -m youtube_agent qa <job_id>                     # sifat nazoratini qayta o'tkazish
    python -m youtube_agent publish <job_id> [--privacy private|unlisted|public] [--reviewed]
    python -m youtube_agent tts-benchmark                   # ovozlarni solishtirish uchun namunalar
    python -m youtube_agent analytics                       # YouTube statistikasini yangilash va xulosa
    python -m youtube_agent auth                            # bir martalik YouTube ruxsati
    python -m youtube_agent set-key NOM                     # .env ga kalit yozish (Bloknotsiz)
    python -m youtube_agent run                             # Telegram + jadval agenti (doimiy)
"""

import argparse
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


def _print_job(job) -> None:
    from .orchestrator import summarize_job
    print("\n" + summarize_job(job))
    if job.has("render/video.mp4"):
        print(f"🎞  Video: {job.path('render/video.mp4')}")
    print(f"📁 Barcha fayllar: {job.root}")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if len(sys.argv) > 1 and sys.argv[1] == "set-key":
        if len(sys.argv) < 3:
            sys.exit("Masalan: python -m youtube_agent set-key PIXABAY_API_KEY")
        return set_key(sys.argv[2].upper())

    ap = argparse.ArgumentParser(prog="python -m youtube_agent", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", nargs="?", default="run")
    ap.add_argument("arg", nargs="?")
    ap.add_argument("--privacy", default=None)
    ap.add_argument("--reviewed", action="store_true", help="needs_review holatidagi videoni ko'rib chiqdim")
    a = ap.parse_args()
    cfg = Config.from_env()
    if a.cmd in ("produce", "test-video", "resume", "qa"):
        mode = "SINOV (arzon model)" if cfg.test_mode else "ISHCHI"
        print(f"Rejim: {mode} | model: {cfg.llm_model} | bitta video chegarasi: ${cfg.max_cost_usd:.2f} | "
              f"avtomatik tuzatishlar: {cfg.max_corrections}")

    if a.cmd == "auth":
        from .youtube import authorize
        authorize(cfg.youtube_client_secret, cfg.youtube_token_file)

    elif a.cmd in ("produce", "test-video"):
        from .factory import build_pipeline
        p = build_pipeline(cfg)
        job = p.new_job(a.arg or cfg.topics[0])
        p.run(job)
        _print_job(job)

    elif a.cmd == "resume":
        from .factory import build_pipeline
        from .jobs import Job
        from .schemas import JobState
        job = Job.load(cfg.jobs_dir, a.arg)
        if job.state in (JobState.needs_review, JobState.qa_failed):
            # tugagan bosqichlar fayllardan aniqlanadi; holatni oxirgi ishchi bosqichga qaytaramiz
            prev = [h["state"] for h in job.meta["history"] if h["state"] not in ("needs_review", "qa_failed")]
            job.meta["state"] = prev[-1] if prev else JobState.planned.value
            job.save()
        p = build_pipeline(cfg)
        spent = float(job.meta.get("costs", {}).get("total", 0))
        if p.s.max_cost_usd:  # avvalgi sarf + yana bir chegara
            p.s.max_cost_usd = round(spent + cfg.max_cost_usd, 2)
            print(f"Avval sarflangan: ~${spent:.3f}. Bu safar yana ${cfg.max_cost_usd:.2f} gacha ruxsat.")
        p.run(job)
        _print_job(job)

    elif a.cmd == "jobs":
        from .jobs import Job
        for jid in Job.list_ids(cfg.jobs_dir):
            j = Job.load(cfg.jobs_dir, jid)
            print(f"{jid}  {j.state.value:13s} {j.meta.get('category', '')}")

    elif a.cmd == "qa":
        from .factory import build_pipeline
        from .jobs import Job
        from .schemas import JobState
        job = Job.load(cfg.jobs_dir, a.arg)
        job.meta["state"] = JobState.rendered.value
        job.save()
        build_pipeline(cfg).run(job)
        _print_job(job)

    elif a.cmd == "publish":
        from .analytics import ChannelDB
        from .jobs import Job
        from .publishing import publish
        from .youtube import YouTube
        job = Job.load(cfg.jobs_dir, a.arg)
        privacy = a.privacy or cfg.youtube_privacy
        if privacy == "scheduled":
            sys.exit("CLI'dan 'scheduled' ishlatilmaydi - private, unlisted yoki public tanlang")
        res = publish(job, YouTube(cfg.youtube_token_file), ChannelDB(cfg.db_path), cfg.youtube_category_id,
                      privacy, None, owner_override=a.reviewed)
        print(f"✅ {res['url']} - {res['youtube_status']}")

    elif a.cmd == "tts-benchmark":
        import os
        from .benchmark import DEFAULT_VOICES, run_benchmark
        out = cfg.data_dir / "tts_benchmark"
        rows = run_benchmark(out, os.environ.get("TTS_BENCHMARK_VOICES", DEFAULT_VOICES), cfg.use_asr,
                             cfg.tts_model, cfg.tts_instructions, cfg.pronunciation_path)
        print(f"\nNamunalar: {out}\n")
        for r in rows:
            if "error" in r:
                print(f"❌ {r['provider']}:{r['voice']} - {r['error']}")
            else:
                sim = f", tanib olish o'xshashligi {r['asr_similarity']}" if "asr_similarity" in r else ""
                print(f"🔊 {r['provider']}:{r['voice']} - {r['duration']}s, ${r['cost_usd']}{sim}\n   {r['file']}")
        print("\nHar bir faylni eshitib ko'ring va eng tabiiy ovozni .env'da tanlang (OPENAI_TTS_VOICE / TTS_PROVIDER).")

    elif a.cmd == "analytics":
        from .analytics import ChannelDB, snapshot_all, summary
        from .youtube import YouTube
        db = ChannelDB(cfg.db_path)
        n = snapshot_all(db, YouTube(cfg.youtube_token_file).creds)
        print(f"{n} ta video yangilandi.\n\n{summary(db) or 'Hali yetarli maʼlumot yoʻq.'}")

    elif a.cmd == "run":
        if not cfg.telegram_token:
            sys.exit("TELEGRAM_BOT_TOKEN .env faylida ko'rsatilmagan")
        from .agent import Agent
        Agent(cfg).run()
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
