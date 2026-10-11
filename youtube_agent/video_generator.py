"""F. AI video generatsiya (ixtiyoriy, standart holatda o'chiq).

Provayderdan mustaqil interfeys: generate_scene_video(prompt, duration_seconds, aspect_ratio, out_path).
Hozirgi realizatsiya: OpenAI Sora (rasmiy `openai` SDK'dagi client.videos API).
AI kadrlar "AI tasvir" deb belgilanadi va hech qachon haqiqiy hujjatli kadr sifatida ko'rsatilmaydi.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .media import probe

log = logging.getLogger(__name__)

SAFETY_SUFFIX = (" Vertical 9:16 documentary-style shot, realistic lighting, no on-screen text, no logos, "
                 "no watermarks, scientifically accurate, do not invent details that are not described.")


@dataclass
class GeneratedVideo:
    path: Path
    provider: str
    model: str
    job_id: str
    seconds: float
    cost_usd: float


class VideoGenerator(Protocol):
    def generate_scene_video(self, prompt: str, duration_seconds: float, out_path: Path,
                             aspect_ratio: str = "9:16") -> GeneratedVideo: ...


class SoraGenerator:
    """OpenAI Sora: 4/8/12 soniyalik klip, vertikal 720x1280."""

    ALLOWED_SECONDS = (4, 8, 12)

    def __init__(self, model: str = "sora-2", price_per_second: float = 0.10, timeout_s: int = 900, attempts: int = 2):
        from openai import OpenAI

        self.client = OpenAI()
        self.model = model
        self.price_per_second = price_per_second
        self.timeout_s = timeout_s
        self.attempts = attempts

    def _seconds(self, wanted: float) -> int:
        for s in self.ALLOWED_SECONDS:
            if s >= wanted:
                return s
        return self.ALLOWED_SECONDS[-1]

    def generate_scene_video(self, prompt: str, duration_seconds: float, out_path: Path,
                             aspect_ratio: str = "9:16") -> GeneratedVideo:
        if aspect_ratio != "9:16":
            raise ValueError("faqat 9:16 qo'llab-quvvatlanadi")
        seconds = self._seconds(duration_seconds)
        last_error = ""
        for attempt in range(1, self.attempts + 1):
            log.info("Sora: %ds video generatsiya (%d-urinish)", seconds, attempt)
            started = time.time()
            video = self.client.videos.create(prompt=prompt + SAFETY_SUFFIX, model=self.model,
                                              seconds=str(seconds), size="720x1280")
            while video.status in ("queued", "in_progress"):
                if time.time() - started > self.timeout_s:
                    raise TimeoutError(f"Sora {self.timeout_s}s ichida tugatmadi (job {video.id})")
                time.sleep(10)
                video = self.client.videos.retrieve(video.id)
            if video.status == "completed":
                content = self.client.videos.download_content(video.id, variant="video")
                content.write_to_file(out_path)
                info = probe(out_path)
                if not info.has_video or info.duration < 1:
                    raise RuntimeError("Sora yaroqsiz fayl qaytardi")
                return GeneratedVideo(out_path, "openai-sora", self.model, video.id, info.duration,
                                      round(seconds * self.price_per_second, 3))
            last_error = str(getattr(video, "error", "") or video.status)
            log.warning("Sora muvaffaqiyatsiz: %s", last_error)
        raise RuntimeError(f"Sora video yaratmadi: {last_error}")


def make_video_generator(provider: str, model: str, price_per_second: float) -> VideoGenerator | None:
    provider = (provider or "").lower()
    if provider in ("", "none", "off", "0"):
        return None
    if provider == "sora":
        return SoraGenerator(model=model or "sora-2", price_per_second=price_per_second)
    raise ValueError(f"Noma'lum AI_VIDEO_PROVIDER: {provider}")
