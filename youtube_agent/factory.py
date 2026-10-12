"""Config'dan quvur komponentlarini yig'ish (agent va CLI uchun umumiy)."""

from __future__ import annotations

from .config import Config
from .llm import LLM, make_llm
from .orchestrator import Pipeline, PipelineSettings
from .quality_gate import QASettings
from .render import RenderSettings
from .subtitles import SubtitleStyle
from .tts import make_tts
from .video_generator import make_video_generator
from .visual_search import VisualSearcher, VisualSettings


def build_llm(cfg: Config) -> LLM:
    return make_llm(cfg.llm_provider, cfg.llm_model, cfg.llm_cheap_model)


def caption_font_name(path: str) -> str:
    from PIL import ImageFont
    try:
        return ImageFont.truetype(path, 10).getname()[0]
    except OSError:
        return "Arial"


def build_pipeline(cfg: Config, llm: LLM | None = None) -> Pipeline:
    llm = llm or build_llm(cfg)
    tts = make_tts(cfg.tts_provider, cfg.tts_voice, cfg.tts_model, cfg.tts_instructions, cfg.tts_rate,
                   cfg.tts_price_per_min)
    video_gen = make_video_generator(cfg.ai_video_provider, cfg.ai_video_model, cfg.ai_video_price_per_sec)
    vs = VisualSettings(pexels_key=cfg.pexels_key, pixabay_key=cfg.pixabay_key,
                        allow_publisher_images=cfg.allow_publisher_images, vision_check=cfg.vision_check,
                        min_relevance=cfg.visual_min_score, font_bold=cfg.headline_font_path,
                        font_regular=cfg.font_path)
    settings = PipelineSettings(
        jobs_dir=cfg.jobs_dir,
        render=RenderSettings(cfg.font_bold_path, cfg.font_path, cfg.headline_font_path),
        min_seconds=cfg.min_seconds, max_seconds=cfg.max_seconds, max_corrections=cfg.max_corrections,
        visual_workers=cfg.visual_workers, max_cost_usd=cfg.max_cost_usd,
        ai_video_enabled=video_gen is not None, music_dir=cfg.music_dir, music_db=cfg.music_db, sfx_dir=cfg.sfx_dir,
        target_lufs=cfg.target_lufs, use_asr=cfg.use_asr, pronunciation_path=cfg.pronunciation_path,
        subtitle_style=SubtitleStyle(font_name=caption_font_name(cfg.font_bold_path)),
        qa=QASettings(min_scores=cfg.qa_min, target_lufs=cfg.target_lufs),
    )
    return Pipeline(settings, llm, tts, lambda: VisualSearcher(vs, llm, video_gen))
