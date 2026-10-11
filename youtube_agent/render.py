"""J. FFmpeg montaj dvigateli.

- Har sahna o'z kadri bilan, davomiyligi ovozdagi o'z gaplariga teng (sinxronlik yo'qolmaydi).
- Kadrni cho'zmaydi: vertikal kadr ekranga to'ldiriladi; gorizontal kadr kenglik bo'yicha sig'diriladi,
  orqasiga o'sha kadrning xira versiyasi qo'yiladi. Rasmlar sekin yaqinlashadi (Ken Burns).
- O'tishlar: odatda toza kesish; "crossfade" faqat rejada so'ralgan joyda. Vaqt siljimaydi.
- Yakuniy fayl: 1080x1920, H.264 High, yuv420p, 30 fps, AAC 48 kHz, faststart.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from .media import probe, run_ffmpeg
from .schemas import AssetMeta, Scene

log = logging.getLogger(__name__)
W, H, FPS = 1080, 1920, 30
ZW, ZH = 1296, 2304  # Ken Burns uchun kattaroq kanvas
XFADE = 0.35
ACCENT = (255, 214, 90)


@dataclass
class RenderSettings:
    font_bold: str
    font_regular: str
    headline_font: str
    crf: int = 20
    preset: str = "medium"


def _font(path: str, size: int, fallback: str = "") -> ImageFont.FreeTypeFont:
    for p in (path, fallback):
        if p:
            try:
                return ImageFont.truetype(p, size)
            except OSError:
                continue
    return ImageFont.load_default(size)


# ------------------------------------------------------------------ rasm kompozitsiyasi
def compose_still(src_path: Path, out: Path, size: tuple[int, int] = (ZW, ZH)) -> Path:
    """Rasmni vertikal kanvasga joylaydi: tik rasm - to'ldiriladi, yotiq - sig'diriladi + xira fon."""
    cw, ch = size
    src = Image.open(src_path).convert("RGB")
    ar = src.width / src.height
    scale = max(cw / src.width, ch / src.height)
    cover = src.resize((int(src.width * scale) + 1, int(src.height * scale) + 1), Image.LANCZOS)
    left, top = (cover.width - cw) // 2, (cover.height - ch) // 2
    cover = cover.crop((left, top, left + cw, top + ch))
    if ar <= 0.8:  # tik yoki deyarli tik - to'liq ekran
        cover.save(out, quality=93)
        return out
    canvas = ImageEnhance.Brightness(cover.filter(ImageFilter.GaussianBlur(45))).enhance(0.35)
    fscale = min(cw * 0.98 / src.width, ch * 0.62 / src.height)
    fg = src.resize((int(src.width * fscale), int(src.height * fscale)), Image.LANCZOS)
    mask = Image.new("L", fg.size, 0)
    f = max(10, int(min(fg.size) * 0.04))
    ImageDraw.Draw(mask).rectangle([f, f, fg.width - f, fg.height - f], fill=255)
    canvas.paste(fg, ((cw - fg.width) // 2, int(ch * 0.47) - fg.height // 2), mask.filter(ImageFilter.GaussianBlur(f / 2)))
    canvas.save(out, quality=93)
    return out


def render_overlay(scene: Scene, ai_label: bool, settings: RenderSettings, out: Path, headline: bool = True) -> Path:
    """Shaffof qatlam: tepada katta yozuv (raqam/kalit so'z) va kerak bo'lsa "AI tasvir" belgisi."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if scene.on_screen_text and headline:
        # matn o'qilishi uchun tepada yumshoq qorong'ilik
        shade = Image.new("L", (1, 520))
        for y in range(520):
            shade.putpixel((0, y), int(150 * (1 - y / 520)))
        img.paste((0, 0, 0, 255), (0, 0, W, 520), shade.resize((W, 520)))
        text = scene.on_screen_text.upper()
        size = 140
        font = _font(settings.headline_font, size, settings.font_bold)
        while d.textlength(text, font=font) > W - 120 and size > 56:
            size -= 6
            font = _font(settings.headline_font, size, settings.font_bold)
        tw = d.textlength(text, font=font)
        y = 230
        d.text(((W - tw) / 2 + 4, y + 5), text, font=font, fill=(0, 0, 0, 170))
        d.text(((W - tw) / 2, y), text, font=font, fill=(*ACCENT, 255))
        if scene.on_screen_subtext:
            sub = scene.on_screen_subtext.upper()
            sfont = _font(settings.font_bold, 34)
            sw = d.textlength(sub, font=sfont)
            d.text(((W - sw) / 2, y + size + 24), sub, font=sfont, fill=(225, 235, 250, 235))
    if ai_label:
        lfont = _font(settings.font_bold, 28)
        label = "AI TASVIR"
        lw = d.textlength(label, font=lfont)
        d.rounded_rectangle([W - lw - 70, 140, W - 40, 190], 12, fill=(0, 0, 0, 150))
        d.text((W - lw - 55, 148), label, font=lfont, fill=(255, 255, 255, 230))
    img.save(out)
    return out


# ---------------------------------------------------------------------- sahna kliplari
def video_framing_filter(width: int, height: int) -> str:
    """Kadrni buzmasdan 1080x1920 ga keltiruvchi filtr ([0:v] -> [v])."""
    if height and width / height <= 0.8:
        return (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,fps={FPS}[v]")
    return (f"[0:v]split=2[a][b];"
            f"[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=30:3,eq=brightness=-0.22[bg];"
            f"[b]scale='min({W},iw*{int(H * 0.62)}/ih)':-2[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2-{int(H * 0.03)},setsar=1,fps={FPS}[v]")


def render_scene(asset: AssetMeta, scene: Scene, dur: float, out: Path, settings: RenderSettings) -> Path:
    work = out.parent
    # grafikada katta yozuv allaqachon bor - takrorlanmasin
    overlay = render_overlay(scene, asset.ai_generated, settings, work / f"overlay_{scene.id:02d}.png",
                             headline=asset.media_type != "graphic")
    frames = max(1, round(dur * FPS))
    if asset.media_type == "video":
        info = probe(Path(asset.local_path))
        start = min(1.0, max(0.0, info.duration - dur - 0.1))  # kirish qismlarini (logo) o'tkazib yuborish
        loop = ["-stream_loop", "-1"] if info.duration - start < dur + 0.1 else []
        flt = video_framing_filter(info.width, info.height)
        run_ffmpeg(*loop, "-ss", f"{start:.2f}", "-i", asset.local_path, "-loop", "1", "-i", str(overlay),
                   "-filter_complex", f"{flt};[1:v]format=rgba[o];[v][o]overlay=0:0:format=auto,format=yuv420p[out]",
                   "-map", "[out]", "-frames:v", str(frames), "-an", "-c:v", "libx264", "-preset", "veryfast",
                   "-crf", "18", str(out))
    else:
        canvas = compose_still(Path(asset.local_path), work / f"still_{scene.id:02d}.jpg")
        zoom = f"zoompan=z='1+0.06*on/{frames}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={W}x{H}:fps={FPS}"
        run_ffmpeg("-loop", "1", "-framerate", str(FPS), "-i", str(canvas), "-loop", "1", "-i", str(overlay),
                   "-filter_complex", f"[0:v]{zoom},setsar=1[v];[1:v]format=rgba[o];"
                                      "[v][o]overlay=0:0:format=auto,format=yuv420p[out]",
                   "-map", "[out]", "-frames:v", str(frames), "-c:v", "libx264", "-preset", "veryfast",
                   "-crf", "18", str(out))
    return out


def scene_durations(bounds: list[float], scenes: list[Scene]) -> list[float]:
    """Sahna davomiyliklari; crossfade bo'lsa oldingi klip XFADE ga uzaytiriladi (vaqt siljimasligi uchun)."""
    durs = [bounds[i + 1] - bounds[i] for i in range(len(scenes))]
    if any(s.transition == "crossfade" for s in scenes[1:]):
        for i in range(len(scenes) - 1):
            durs[i] += XFADE if scenes[i + 1].transition == "crossfade" else 0.04
    return durs


def assemble(clips: list[Path], scenes: list[Scene], bounds: list[float], out: Path) -> Path:
    if not any(s.transition == "crossfade" for s in scenes[1:]):
        lst = out.with_name("clips.txt")
        lst.write_text("".join(f"file '{c.name}'\n" for c in clips), encoding="utf-8")
        run_ffmpeg("-f", "concat", "-safe", "0", "-i", lst.name, "-c", "copy", out.name, cwd=out.parent)
        return out
    inputs, parts, last = [], [], "[0:v]"
    for c in clips:
        inputs += ["-i", str(c)]
    for k in range(1, len(clips)):
        d = XFADE if scenes[k].transition == "crossfade" else 0.04
        parts.append(f"{last}[{k}:v]xfade=transition=fade:duration={d}:offset={bounds[k]:.3f}[x{k}]")
        last = f"[x{k}]"
    run_ffmpeg(*inputs, "-filter_complex", ";".join(parts), "-map", last, "-c:v", "libx264", "-preset", "veryfast",
               "-crf", "18", "-pix_fmt", "yuv420p", str(out))
    return out


def finalize(video: Path, audio: Path, ass: Path, total: float, out: Path, settings: RenderSettings,
             fonts: list[str]) -> Path:
    work = out.parent
    fdir = work / "fonts"
    fdir.mkdir(exist_ok=True)
    for f in fonts:
        if f and Path(f).exists():
            shutil.copy(f, fdir / Path(f).name)
    if ass.parent != work:
        shutil.copy(ass, work / ass.name)
    vf = (f"tpad=stop_mode=clone:stop_duration=1,ass={ass.name}:fontsdir=fonts,"
          "drawbox=x=60:y=1890:w=960:h=6:color=white@0.25:t=fill,"
          f"drawbox=x=60:y=1890:w='960*t/{total:.3f}':h=6:color=0xE8204F:t=fill,format=yuv420p")
    run_ffmpeg("-i", str(video), "-i", str(audio), "-map", "0:v", "-map", "1:a", "-vf", vf, "-t", f"{total:.3f}",
               "-r", str(FPS), "-c:v", "libx264", "-profile:v", "high", "-preset", settings.preset,
               "-crf", str(settings.crf), "-g", str(FPS * 2), "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", out.name, cwd=work)
    return out
