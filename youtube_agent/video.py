"""Ssenariydan vertikal YouTube Shorts yasash (ilmiy-yangilik uslubi).

Har sahna: qora fon + o'rtada mavzuga oid rasm (sekin yaqinlashadi), tepada katta rangli raqam/kalit so'z
va kichik izoh, pastda so'zma-so'z yonadigan subtitr, eng pastda progress chizig'i. Ovoz: edge-tts.
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import edge_tts
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from .content import VideoPlan
from .images import ImageFinder

log = logging.getLogger(__name__)

W, H, FPS = 1080, 1920, 30
ZOOM_W, ZOOM_H = 1296, 2304  # fon 1.2x kattaroq chiziladi, zoompan kichraytiradi
ACCENTS = {
    "orange": (255, 168, 76),
    "cyan": (110, 200, 255),
    "white": (255, 255, 255),
    "yellow": (255, 214, 90),
}
SUB_COLOR = (110, 200, 255)
HIGHLIGHT_ASS = "&H00FFC86E&"  # subtitrdagi joriy so'z (moviy), ASS formatida BGR


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
    headline_font_path: str
    pixabay_key: str = ""
    music_dir: str = ""
    ai_images: bool = False
    stock_fallback: bool = False


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


class VideoMaker:
    def __init__(self, settings: ShortsSettings):
        self.s = settings

    def _font(self, path: str, size: int) -> ImageFont.FreeTypeFont:
        for p in (path, self.s.font_bold_path):
            try:
                return ImageFont.truetype(p, size)
            except OSError:
                continue
        return ImageFont.load_default(size)

    # ------------------------------------------------------------------ ovoz
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

    # --------------------------------------------------------------- tasvir
    @staticmethod
    def render_background(image: Path | None, accent: tuple[int, int, int], out: Path) -> None:
        """Qora fon, xira kattalashtirilgan rasm, o'rtada chetlari silliq so'nadigan asosiy rasm."""
        canvas = Image.new("RGB", (ZOOM_W, ZOOM_H), (0, 0, 0))
        if image:
            src = Image.open(image).convert("RGB")
            # orqa fon: ekranni to'ldiradi, xira va qorong'i
            scale = max(ZOOM_W / src.width, ZOOM_H / src.height)
            bg = src.resize((int(src.width * scale) + 1, int(src.height * scale) + 1))
            left, top = (bg.width - ZOOM_W) // 2, (bg.height - ZOOM_H) // 2
            bg = bg.crop((left, top, left + ZOOM_W, top + ZOOM_H)).filter(ImageFilter.GaussianBlur(40))
            canvas = ImageEnhance.Brightness(bg).enhance(0.28)
            # asosiy rasm: kenglik bo'ylab, markazda
            box_w, box_h = int(ZOOM_W * 0.98), int(ZOOM_H * 0.58)
            scale = min(box_w / src.width, box_h / src.height)
            fg = src.resize((int(src.width * scale), int(src.height * scale)))
            mask = Image.new("L", fg.size, 0)
            feather = max(12, int(min(fg.size) * 0.08))
            ImageDraw.Draw(mask).rectangle([feather, feather, fg.width - feather, fg.height - feather], fill=255)
            mask = mask.filter(ImageFilter.GaussianBlur(feather / 2))
            canvas.paste(fg, ((ZOOM_W - fg.width) // 2, int(ZOOM_H * 0.53) - fg.height // 2), mask)
        else:  # rasm yo'q: markazda xira rangli nur
            glow = Image.new("RGB", (ZOOM_W, ZOOM_H), (0, 0, 0))
            d = ImageDraw.Draw(glow)
            cx, cy, r = ZOOM_W // 2, int(ZOOM_H * 0.53), int(ZOOM_W * 0.35)
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=tuple(int(c * 0.35) for c in accent))
            canvas = glow.filter(ImageFilter.GaussianBlur(160))
        # matn o'qilishi uchun tepada va pastda qorong'i gradient
        shade = Image.new("L", (1, ZOOM_H))
        for y in range(ZOOM_H):
            t = y / ZOOM_H
            shade.putpixel((0, y), int(200 * max(0.0, 1 - t / 0.3) + 160 * max(0.0, (t - 0.75) / 0.25)))
        canvas.paste((0, 0, 0), (0, 0, ZOOM_W, ZOOM_H), shade.resize((ZOOM_W, ZOOM_H)))
        canvas.save(out, quality=93)

    def render_text(self, headline: str, subline: str, accent: tuple[int, int, int], out: Path) -> None:
        """Tepada katta yozuv (masalan '8 DAQIQA') va uning tagida harflari keng izoh."""
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        headline = headline.upper().strip()
        size = 150
        font = self._font(self.s.headline_font_path, size)
        while d.textlength(headline, font=font) > W - 110 and size > 60:
            size -= 6
            font = self._font(self.s.headline_font_path, size)
        tw = d.textlength(headline, font=font)
        y = 250
        d.text(((W - tw) / 2 + 4, y + 5), headline, font=font, fill=(0, 0, 0, 160))
        d.text(((W - tw) / 2, y), headline, font=font, fill=(*accent, 255))
        # izoh: kichik, katta harflar, keng oraliq
        sub = subline.upper().strip()
        sfont = self._font(self.s.font_bold_path, 34)
        spacing = 7
        widths = [d.textlength(ch, font=sfont) for ch in sub]
        total = sum(widths) + spacing * max(len(sub) - 1, 0)
        while total > W - 120 and spacing > 1:
            spacing -= 1
            total = sum(widths) + spacing * max(len(sub) - 1, 0)
        x, sy = (W - total) / 2, y + size + 28
        sub_color = SUB_COLOR if accent == ACCENTS["white"] else accent
        for ch, cw in zip(sub, widths):
            d.text((x, sy), ch, font=sfont, fill=(*sub_color, 235))
            x += cw + spacing
        img.save(out)

    def _segment(self, bg: Path, text: Path, audio: Path, dur: float, out: Path) -> None:
        frames = int(dur * FPS) + 2
        flt = (
            f"[0:v]zoompan=z='1+0.07*on/{frames}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":d=1:s={W}x{H}:fps={FPS},setsar=1[bg];"
            "[1:v]format=rgba,fade=in:st=0:d=0.25:alpha=1[t];"
            "[bg][t]overlay=0:0:format=auto,format=yuv420p[v]"
        )
        _ffmpeg("-loop", "1", "-framerate", str(FPS), "-i", str(bg),
                "-loop", "1", "-framerate", str(FPS), "-i", str(text),
                "-i", str(audio), "-t", f"{dur:.2f}", "-filter_complex", flt, "-af", "apad",
                "-map", "[v]", "-map", "2:a", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2", str(out))

    # ------------------------------------------------------------ subtitrlar
    def _write_ass(self, words: list[Word], font_name: str, out: Path) -> None:
        header = (
            "[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\nWrapStyle: 0\n\n"
            "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
            "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, "
            "Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
            f"Style: Cap,{font_name},66,&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,-1,0,0,0,100,100,0,0,1,4,2,2,90,90,560,1\n\n"
            "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        )
        lines = [header]
        chunks, cur = [], []
        for w in words:  # 1-2 so'zdan, tinish belgisida bo'linadi
            cur.append(w)
            if len(cur) == 2 or re.search(r"[.!?,:;]$", w.text):
                chunks.append(cur)
                cur = []
        if cur:
            chunks.append(cur)
        for ci, chunk in enumerate(chunks):
            chunk_end = chunks[ci + 1][0].start if ci + 1 < len(chunks) else chunk[-1].end + 0.3
            for wi, w in enumerate(chunk):
                end = chunk[wi + 1].start if wi + 1 < len(chunk) else chunk_end
                parts = [f"{{\\c{HIGHLIGHT_ASS}}}{_ass_escape(o.text)}{{\\c&H00FFFFFF&}}" if wj == wi
                         else _ass_escape(o.text) for wj, o in enumerate(chunk)]
                pop = "{\\fscx108\\fscy108\\t(0,80,\\fscx100\\fscy100)}" if wi == 0 else ""
                lines.append(f"Dialogue: 0,{_ass_time(w.start)},{_ass_time(end)},Cap,,0,0,0,,{pop}{' '.join(parts)}\n")
        out.write_text("".join(lines), encoding="utf-8")

    # ---------------------------------------------------------------- yig'ish
    def build(self, plan: VideoPlan, category: str, workdir: Path) -> tuple[Path, Path]:
        """Shorts videoni yasaydi, (video_path, muqova_path) qaytaradi. Rasm mualliflari tavsifga qo'shiladi."""
        workdir.mkdir(parents=True, exist_ok=True)
        finder = ImageFinder(category, plan.sources, self.s.pixabay_key, self.s.ai_images, self.s.stock_fallback)
        segments, all_words, offset = [], [], 0.0
        last_image: Path | None = None
        for i, scene in enumerate(plan.scenes):
            log.info("Sahna %d/%d: %s", i + 1, len(plan.scenes), scene.headline)
            audio = workdir / f"s{i:02d}.mp3"
            words = self.synthesize(scene.narration, audio)
            dur = _duration(audio) + 0.12
            found = finder.find(scene.image_source, scene.image_query, scene.image_prompt, workdir / f"img{i:02d}")
            image = found.path if found else last_image  # topilmasa oldingi sahna rasmi davom etadi
            last_image = image or last_image
            accent = ACCENTS.get(scene.accent, ACCENTS["white"])
            bg, text, seg = workdir / f"bg{i:02d}.jpg", workdir / f"tx{i:02d}.png", workdir / f"s{i:02d}.mp4"
            self.render_background(image, accent, bg)
            self.render_text(scene.headline, scene.subline, accent, text)
            self._segment(bg, text, audio, dur, seg)
            all_words += [Word(w.start + offset, w.end + offset, w.text) for w in words]
            offset += _duration(seg)
            segments.append(seg)

        (workdir / "concat.txt").write_text("".join(f"file '{s.name}'\n" for s in segments), encoding="utf-8")
        _ffmpeg("-f", "concat", "-safe", "0", "-i", "concat.txt", "-c", "copy", "joined.mp4", cwd=workdir)
        total = _duration(workdir / "joined.mp4")

        fonts = workdir / "fonts"  # libass shriftni shu papkadan topadi
        fonts.mkdir(exist_ok=True)
        for fp in {self.s.font_path, self.s.font_bold_path}:
            if Path(fp).exists():
                shutil.copy(fp, fonts / Path(fp).name)
        try:
            font_name = ImageFont.truetype(self.s.font_bold_path, 10).getname()[0]
        except OSError:
            font_name = "Arial"
        self._write_ass(all_words, font_name, workdir / "captions.ass")

        vf = ("ass=captions.ass:fontsdir=fonts,"
              "drawbox=x=40:y=1896:w=1000:h=6:color=white@0.25:t=fill,"
              f"drawbox=x=40:y=1896:w='1000*t/{total:.2f}':h=6:color=0xE8204F:t=fill")
        music = sorted(Path(self.s.music_dir).glob("*.mp3")) if self.s.music_dir and Path(self.s.music_dir).is_dir() else []
        args = ["-i", "joined.mp4"]
        if music:
            args += ["-stream_loop", "-1", "-i", str(Path(random.choice(music)).resolve()),
                     "-filter_complex", "[1:a]volume=0.12[m];[0:a][m]amix=inputs=2:duration=first:normalize=0[a]",
                     "-map", "0:v", "-map", "[a]"]
        args += ["-vf", vf, "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
                 "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "video.mp4"]
        _ffmpeg(*args, cwd=workdir)

        _ffmpeg("-ss", "0.6", "-i", "video.mp4", "-frames:v", "1", "-q:v", "3", "thumbnail.jpg", cwd=workdir)
        if finder.credits and "Rasmlar:" not in plan.description:
            plan.description = f"{plan.description}\n\nRasmlar: {', '.join(finder.credits)}"[:4900]
        return workdir / "video.mp4", workdir / "thumbnail.jpg"
