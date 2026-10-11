"""Generatsiya qilinadigan grafikalar: raqam yoki taqqoslashni tushuntiruvchi kartochka.

Mos video yoki rasm topilmaganda aloqasiz kadr o'rniga ishlatiladi - u aynan sahnadagi faktni ko'rsatadi.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1080, 1920
PALETTES = [((18, 32, 70), (4, 6, 18), (110, 200, 255)), ((60, 22, 70), (12, 4, 20), (255, 168, 76)),
            ((14, 52, 48), (2, 14, 14), (120, 230, 190)), ((70, 40, 12), (18, 8, 2), (255, 214, 90))]


def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default(size)


def render_graphic(title: str, subtitle: str, body: str, out: Path, font_bold: str, font_regular: str,
                   palette_index: int = 0) -> Path:
    """Gradient fon, markazda katta raqam/kalit so'z, tagida izoh va qisqa tushuntirish."""
    top, bottom, accent = PALETTES[palette_index % len(PALETTES)]
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        d.line([(0, y), (W, y)], fill=tuple(int(top[i] * (1 - t) + bottom[i] * t) for i in range(3)))
    glow = Image.new("RGB", (W, H), (0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([W * 0.1, H * 0.3, W * 0.9, H * 0.62], fill=tuple(int(c * 0.45) for c in accent))
    img = Image.blend(img, glow.filter(ImageFilter.GaussianBlur(140)), 0.55)
    d = ImageDraw.Draw(img)

    title = (title or "").upper().strip()
    size = 190
    font = _font(font_bold, size)
    while title and d.textlength(title, font=font) > W - 120 and size > 70:
        size -= 8
        font = _font(font_bold, size)
    y = int(H * 0.40)
    if title:
        tw = d.textlength(title, font=font)
        d.text(((W - tw) / 2, y), title, font=font, fill=accent)
        y += size + 30
    if subtitle:
        sfont = _font(font_bold, 46)
        for line in textwrap.wrap(subtitle.upper(), 28)[:2]:
            tw = d.textlength(line, font=sfont)
            d.text(((W - tw) / 2, y), line, font=sfont, fill=(235, 240, 250))
            y += 62
    if body:
        bfont = _font(font_regular, 40)
        y += 30
        for line in textwrap.wrap(body, 36)[:4]:
            tw = d.textlength(line, font=bfont)
            d.text(((W - tw) / 2, y), line, font=bfont, fill=(200, 210, 225))
            y += 54
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, quality=94)
    return out
