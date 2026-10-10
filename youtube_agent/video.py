"""Ssenariydan vertikal YouTube Shorts yasash.

Har sahna: stok-video (Pexels) yoki rasm + diktor ovozi (edge-tts).
Ustiga so'zma-so'z yonadigan katta subtitrlar (ASS/libass), tepada hook yozuvi, ixtiyoriy fon musiqasi.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import random
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import edge_tts
import httpx
from PIL import Image, ImageDraw, ImageFont

from .content import VideoPlan

log = logging.getLogger(__name__)

W, H, FPS = 1080, 1920, 30
THEMES = {  # rasm topilmasa fon ranglari
    "Tibbiyot": ((10, 60, 90), (5, 20, 35)),
    "Ilm-fan": ((40, 20, 90), (10, 5, 30)),
    "Sun'iy intellekt": ((15, 25, 60), (0, 0, 10)),
    "Qiziqarli faktlar": ((90, 30, 40), (25, 5, 10)),
}


@dataclass
class Word:
    start: float
    end: float
    text: str


@dataclass
class ShortsSettings:
    voice: str
    tts_rate: str
    font_path: str
    font_bold_path: str
    pexels_key: str = ""
    music_dir: str = ""
    ai_images: bool = False


# ------------------------------------------------------------------ yordamchilar
def _ffmpeg(*args: str, cwd: Path | None = None) -> None:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True, cwd=cwd)


def _duration(path: Path) -> float:
    res = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(res.stdout.strip())


def _ass_time(t: float) -> str:
    t = max(t, 0)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _ass_escape(text: str) -> str:
    return text.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")


# ------------------------------------------------------------------- vizuallar
class Visuals:
    """Sahna uchun fon: Pexels video -> Pexels rasm -> AI rasm -> rangli fon."""

    def __init__(self, settings: ShortsSettings):
        self.s = settings
        self.http = httpx.Client(timeout=60, follow_redirects=True)
        self.used: set[int] = set()

    def _pexels(self, url: str, query: str) -> dict:
        resp = self.http.get(url, params={"query": query, "orientation": "portrait", "per_page": 10},
                             headers={"Authorization": self.s.pexels_key})
        resp.raise_for_status()
        return resp.json()

    def _download(self, url: str, out: Path) -> Path:
        with self.http.stream("GET", url) as r:
            r.raise_for_status()
            with open(out, "wb") as f:
                for chunk in r.iter_bytes(1 << 16):
                    f.write(chunk)
        return out

    def pexels_video(self, query: str, out: Path) -> Path | None:
        for v in self._pexels("https://api.pexels.com/videos/search", query).get("videos", []):
            if v["id"] in self.used or v.get("width", 0) > v.get("height", 1):
                continue
            files = [f for f in v.get("video_files", [])
                     if f.get("height") and f["height"] >= 1280 and f["height"] >= f.get("width", 0)]
            if not files:
                continue
            best = min(files, key=lambda f: abs(f["height"] - 1920))
            self.used.add(v["id"])
            return self._download(best["link"], out)
        return None

    def pexels_photo(self, query: str, out: Path) -> Path | None:
        for p in self._pexels("https://api.pexels.com/v1/search", query).get("photos", []):
            if p["id"] in self.used:
                continue
            self.used.add(p["id"])
            return self._download(p["src"].get("large2x") or p["src"]["original"], out)
        return None

    def ai_image(self, prompt: str, out: Path) -> Path | None:
        from openai import OpenAI

        resp = OpenAI().images.generate(model="gpt-image-1", prompt=f"{prompt}. Vertical, cinematic, no text.",
                                        size="1024x1536")
        out.write_bytes(base64.b64decode(resp.data[0].b64_json))
        return out

    def fallback(self, category: str, out: Path) -> Path:
        top, bottom = THEMES.get(category, ((30, 40, 70), (5, 5, 15)))
        img = Image.new("RGB", (W, H))
        draw = ImageDraw.Draw(img)
        for y in range(H):
            t = y / H
            draw.line([(0, y), (W, y)], fill=tuple(int(top[i] * (1 - t) + bottom[i] * t) for i in range(3)))
        img.save(out)
        return out

    def get(self, query: str, image_prompt: str, category: str, base: Path) -> tuple[Path, bool]:
        """(fayl, video_mi) qaytaradi."""
        attempts = []
        if self.s.pexels_key:
            attempts += [(self.pexels_video, query, base.with_suffix(".mp4"), True),
                         (self.pexels_photo, query, base.with_suffix(".jpg"), False)]
        if self.s.ai_images:
            attempts.append((self.ai_image, image_prompt, base.with_suffix(".png"), False))
        for fn, arg, out, is_video in attempts:
            try:
                path = fn(arg, out)
                if path:
                    return path, is_video
            except Exception as e:
                log.warning("Vizual topilmadi (%s, %s): %s", fn.__name__, arg, e)
        return self.fallback(category, base.with_suffix(".png")), False


# ------------------------------------------------------------------- yasovchi
class VideoMaker:
    def __init__(self, settings: ShortsSettings):
        self.s = settings
        self.visuals = Visuals(settings)

    async def _tts(self, text: str, out: Path) -> list[Word]:
        comm = edge_tts.Communicate(text, self.s.voice, rate=self.s.tts_rate, boundary="WordBoundary")
        words: list[Word] = []
        with open(out, "wb") as f:
            async for chunk in comm.stream():
                if chunk["type"] == "audio":
                    f.write(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    start = chunk["offset"] / 1e7
                    words.append(Word(start, start + chunk["duration"] / 1e7, chunk["text"]))
        return words

    def synthesize(self, text: str, out: Path) -> list[Word]:
        words = asyncio.run(self._tts(text, out))
        if not words:  # ovoz so'z vaqtlarini bermasa - uzunligiga qarab taqsimlaymiz
            tokens = text.split()
            total = _duration(out)
            weights = [len(t) + 2 for t in tokens]
            t, words = 0.0, []
            for tok, wgt in zip(tokens, weights):
                d = total * wgt / sum(weights)
                words.append(Word(t, t + d, tok))
                t += d
        return words

    def _segment(self, visual: Path, is_video: bool, audio: Path, dur: float, out: Path) -> None:
        frames = int(dur * FPS) + 1
        if is_video:
            vin = ["-stream_loop", "-1", "-i", str(visual)]
            vf = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS},setsar=1"
        else:  # rasm: sekin yaqinlashish (Ken Burns)
            vin = ["-i", str(visual)]
            vf = (f"scale={W * 2}:{H * 2}:force_original_aspect_ratio=increase,crop={W * 2}:{H * 2},"
                  f"zoompan=z='min(zoom+0.0009,1.18)':d={frames}:s={W}x{H}:fps={FPS}"
                  ":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)',setsar=1")
        _ffmpeg(*vin, "-i", str(audio), "-t", f"{dur:.2f}", "-vf", vf, "-af", "apad",
                "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2", str(out))

    def _write_ass(self, words: list[Word], hook: str, font_name: str, out: Path) -> None:
        header = (
            "[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\nWrapStyle: 0\n\n"
            "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
            "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, "
            "Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
            f"Style: Cap,{font_name},96,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,7,3,2,80,80,620,1\n"
            f"Style: Hook,{font_name},82,&H00000000,&H00000000,&H0000E5FF,&H0000E5FF,-1,0,0,0,100,100,0,0,3,18,0,8,70,70,260,1\n\n"
            "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        )
        lines = [header]
        if hook:
            lines.append(f"Dialogue: 1,{_ass_time(0)},{_ass_time(2.8)},Hook,,0,0,0,,"
                         f"{{\\fad(150,250)}}{_ass_escape(hook.upper())}\n")
        # so'zlarni 1-3 tadan guruhlaymiz, tinish belgisida bo'lamiz
        chunks, cur = [], []
        for w in words:
            cur.append(w)
            if len(cur) == 3 or re.search(r"[.!?,:;]$", w.text):
                chunks.append(cur)
                cur = []
        if cur:
            chunks.append(cur)
        for ci, chunk in enumerate(chunks):
            chunk_end = chunks[ci + 1][0].start if ci + 1 < len(chunks) else chunk[-1].end + 0.3
            for wi, w in enumerate(chunk):
                end = chunk[wi + 1].start if wi + 1 < len(chunk) else chunk_end
                parts = []
                for wj, other in enumerate(chunk):
                    t = _ass_escape(other.text.upper())
                    parts.append(f"{{\\c&H0000E5FF&}}{t}{{\\c&H00FFFFFF&}}" if wj == wi else t)
                pop = "{\\fscx112\\fscy112\\t(0,90,\\fscx100\\fscy100)}" if wi == 0 else ""
                lines.append(f"Dialogue: 0,{_ass_time(w.start)},{_ass_time(end)},Cap,,0,0,0,,{pop}{' '.join(parts)}\n")
        out.write_text("".join(lines), encoding="utf-8")

    def build(self, plan: VideoPlan, category: str, workdir: Path) -> tuple[Path, Path]:
        """Shorts videoni yasaydi, (video_path, muqova_path) qaytaradi."""
        workdir.mkdir(parents=True, exist_ok=True)
        segments, all_words, offset = [], [], 0.0
        for i, scene in enumerate(plan.scenes):
            log.info("Sahna %d/%d: %s", i + 1, len(plan.scenes), scene.visual_query)
            audio = workdir / f"s{i:02d}.mp3"
            words = self.synthesize(scene.narration, audio)
            dur = _duration(audio) + 0.15
            visual, is_video = self.visuals.get(scene.visual_query, scene.image_prompt, category, workdir / f"v{i:02d}")
            seg = workdir / f"s{i:02d}.mp4"
            self._segment(visual, is_video, audio, dur, seg)
            all_words += [Word(w.start + offset, w.end + offset, w.text) for w in words]
            offset += _duration(seg)
            segments.append(seg)

        (workdir / "concat.txt").write_text("".join(f"file '{s.name}'\n" for s in segments), encoding="utf-8")
        _ffmpeg("-f", "concat", "-safe", "0", "-i", "concat.txt", "-c", "copy", "joined.mp4", cwd=workdir)

        # subtitrlar uchun shriftni ish papkasiga ko'chiramiz (libass shu yerdan topadi)
        fonts = workdir / "fonts"
        fonts.mkdir(exist_ok=True)
        for fp in {self.s.font_path, self.s.font_bold_path}:
            if Path(fp).exists():
                shutil.copy(fp, fonts / Path(fp).name)
        try:
            font_name = ImageFont.truetype(self.s.font_bold_path, 10).getname()[0]
        except OSError:
            font_name = "Arial"
        self._write_ass(all_words, plan.hook_text, font_name, workdir / "captions.ass")

        music = sorted(Path(self.s.music_dir).glob("*.mp3")) if self.s.music_dir and Path(self.s.music_dir).is_dir() else []
        args = ["-i", "joined.mp4"]
        if music:
            args += ["-stream_loop", "-1", "-i", str(Path(random.choice(music)).resolve()),
                     "-filter_complex", "[1:a]volume=0.12[m];[0:a][m]amix=inputs=2:duration=first:normalize=0[a]",
                     "-map", "0:v", "-map", "[a]"]
        args += ["-vf", "ass=captions.ass:fontsdir=fonts", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                 "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "video.mp4"]
        _ffmpeg(*args, cwd=workdir)

        thumb = workdir / "thumbnail.jpg"
        _ffmpeg("-ss", "1", "-i", "video.mp4", "-frames:v", "1", "-q:v", "3", "thumbnail.jpg", cwd=workdir)
        return workdir / "video.mp4", thumb
