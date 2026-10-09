"""Ssenariydan video yasash: ovoz (edge-tts) + slaydlar (Pillow) + ffmpeg."""

from __future__ import annotations

import asyncio
import logging
import subprocess
import textwrap
from pathlib import Path

import edge_tts
from PIL import Image, ImageDraw, ImageFont

from .content import Scene, VideoPlan

log = logging.getLogger(__name__)

W, H = 1920, 1080
THEMES = {  # kategoriya -> (yuqori rang, pastki rang, aksent)
    "Tibbiyot": ((10, 60, 90), (5, 20, 35), (80, 220, 200)),
    "Ilm-fan": ((40, 20, 90), (10, 5, 30), (255, 190, 70)),
    "Sun'iy intellekt": ((15, 25, 60), (0, 0, 10), (90, 160, 255)),
    "Qiziqarli faktlar": ((90, 30, 40), (25, 5, 10), (255, 210, 90)),
}
DEFAULT_THEME = ((30, 40, 70), (5, 5, 15), (120, 200, 255))


class VideoMaker:
    def __init__(self, voice: str, font_path: str, font_bold_path: str):
        self.voice = voice
        self.font_path = font_path
        self.font_bold_path = font_bold_path

    def _font(self, size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
        try:
            return ImageFont.truetype(self.font_bold_path if bold else self.font_path, size)
        except OSError:
            return ImageFont.load_default(size)

    @staticmethod
    def _background(theme) -> Image.Image:
        top, bottom, _ = theme
        img = Image.new("RGB", (W, H))
        draw = ImageDraw.Draw(img)
        for y in range(H):
            t = y / H
            draw.line([(0, y), (W, y)], fill=tuple(int(top[i] * (1 - t) + bottom[i] * t) for i in range(3)))
        return img

    def render_slide(self, scene: Scene, idx: int, total: int, category: str, out: Path) -> None:
        theme = THEMES.get(category, DEFAULT_THEME)
        img = self._background(theme)
        draw = ImageDraw.Draw(img)
        accent = theme[2]
        draw.text((120, 80), category.upper(), font=self._font(36, True), fill=accent)
        y = 170
        for line in textwrap.wrap(scene.heading, 32):
            draw.text((120, y), line, font=self._font(84, True), fill="white")
            y += 105
        draw.rectangle([120, y + 20, 360, y + 30], fill=accent)
        y += 90
        for bullet in scene.bullets[:4]:
            lines = textwrap.wrap(bullet, 58)
            draw.ellipse([125, y + 18, 147, y + 40], fill=accent)
            for line in lines:
                draw.text((180, y), line, font=self._font(50), fill=(230, 235, 245))
                y += 66
            y += 24
        draw.rectangle([0, H - 12, int(W * (idx + 1) / total), H], fill=accent)  # progress
        img.save(out)

    def render_thumbnail(self, plan: VideoPlan, category: str, out: Path) -> None:
        theme = THEMES.get(category, DEFAULT_THEME)
        img = self._background(theme).resize((1280, 720))
        draw = ImageDraw.Draw(img)
        lines = textwrap.wrap(plan.thumbnail_text.upper(), 14)[:3]
        y = (720 - len(lines) * 150) // 2
        for line in lines:
            font = self._font(130, True)
            w = draw.textlength(line, font=font)
            draw.text(((1280 - w) / 2, y), line, font=font, fill="white", stroke_width=6, stroke_fill="black")
            y += 150
        draw.rectangle([0, 690, 1280, 720], fill=theme[2])
        img.save(out, quality=92)

    def synthesize(self, text: str, out: Path) -> None:
        asyncio.run(edge_tts.Communicate(text, self.voice).save(str(out)))

    @staticmethod
    def _duration(path: Path) -> float:
        res = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, check=True,
        )
        return float(res.stdout.strip())

    @staticmethod
    def _ffmpeg(*args: str) -> None:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)

    def build(self, plan: VideoPlan, category: str, workdir: Path) -> tuple[Path, Path]:
        """Videoni va muqovani yasaydi, (video_path, thumbnail_path) qaytaradi."""
        workdir.mkdir(parents=True, exist_ok=True)
        segments = []
        for i, scene in enumerate(plan.scenes):
            slide, audio, seg = workdir / f"s{i:02d}.png", workdir / f"s{i:02d}.mp3", workdir / f"s{i:02d}.mp4"
            log.info("Sahna %d/%d", i + 1, len(plan.scenes))
            self.render_slide(scene, i, len(plan.scenes), category, slide)
            self.synthesize(scene.narration, audio)
            dur = self._duration(audio) + 0.7  # sahnalar orasida kichik pauza
            self._ffmpeg(
                "-loop", "1", "-framerate", "30", "-i", str(slide), "-i", str(audio),
                "-af", "apad", "-t", f"{dur:.2f}",
                "-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p", "-r", "30",
                "-c:a", "aac", "-b:a", "192k", "-ar", "44100", str(seg),
            )
            segments.append(seg)
        concat = workdir / "concat.txt"
        concat.write_text("".join(f"file '{s.name}'\n" for s in segments), encoding="utf-8")
        video = workdir / "video.mp4"
        self._ffmpeg("-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", "-movflags", "+faststart", str(video))
        thumb = workdir / "thumbnail.jpg"
        self.render_thumbnail(plan, category, thumb)
        return video, thumb
