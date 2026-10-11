"""FFmpeg/FFprobe bilan xavfsiz ishlash uchun yordamchilar."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

log = logging.getLogger(__name__)


class MediaError(RuntimeError):
    pass


def run_ffmpeg(*args: str, cwd: Path | None = None, timeout: int = 900) -> str:
    """ffmpeg'ni ishga tushiradi; xato bo'lsa stderr'ning oxirini ko'rsatadi."""
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args]
    try:
        res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise MediaError(f"ffmpeg vaqt chegarasidan oshdi ({timeout}s)") from e
    if res.returncode != 0:
        raise MediaError(f"ffmpeg xatosi: {res.stderr.strip()[-1500:]}")
    return res.stderr


def run_ffmpeg_analysis(*args: str, timeout: int = 600) -> str:
    """Tahlil filtrlarini (blackdetect, ebur128...) ishga tushiradi va stderr matnini qaytaradi."""
    cmd = ["ffmpeg", "-hide_banner", "-nostats", *args, "-f", "null", "-"]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if res.returncode != 0:
        raise MediaError(f"ffmpeg tahlil xatosi: {res.stderr.strip()[-800:]}")
    return res.stderr


@dataclass
class MediaInfo:
    duration: float
    width: int = 0
    height: int = 0
    fps: float = 0.0
    vcodec: str = ""
    pix_fmt: str = ""
    acodec: str = ""
    sample_rate: int = 0
    has_video: bool = False
    has_audio: bool = False
    size_bytes: int = 0


def probe(path: Path) -> MediaInfo:
    path = Path(path)
    if not path.exists() or path.stat().st_size == 0:
        raise MediaError(f"fayl yo'q yoki bo'sh: {path}")
    res = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
                         capture_output=True, text=True, timeout=60)
    if res.returncode != 0:
        raise MediaError(f"ffprobe faylni o'qiy olmadi: {path.name}: {res.stderr.strip()[-300:]}")
    data = json.loads(res.stdout)
    info = MediaInfo(duration=float(data.get("format", {}).get("duration") or 0), size_bytes=path.stat().st_size)
    for s in data.get("streams", []):
        if s.get("codec_type") == "video" and not info.has_video:
            info.has_video = True
            info.width, info.height = int(s.get("width") or 0), int(s.get("height") or 0)
            info.vcodec, info.pix_fmt = s.get("codec_name", ""), s.get("pix_fmt", "")
            num, _, den = (s.get("avg_frame_rate") or s.get("r_frame_rate") or "0/1").partition("/")
            info.fps = float(num) / float(den or 1) if float(den or 1) else 0.0
            if not info.duration and s.get("duration"):
                info.duration = float(s["duration"])
        elif s.get("codec_type") == "audio" and not info.has_audio:
            info.has_audio = True
            info.acodec, info.sample_rate = s.get("codec_name", ""), int(s.get("sample_rate") or 0)
    return info


def duration(path: Path) -> float:
    return probe(path).duration


def is_image(path: Path) -> bool:
    return Path(path).suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")


def extract_frames(path: Path, out_dir: Path, count: int = 3, width: int = 512, prefix: str = "f") -> list[Path]:
    """Video'dan teng oraliqdagi kadrlar (rasm bo'lsa - o'zi) JPEG ko'rinishida."""
    out_dir.mkdir(parents=True, exist_ok=True)
    if is_image(path):
        img = Image.open(path).convert("RGB")
        img.thumbnail((width, width * 2))
        out = out_dir / f"{prefix}0.jpg"
        img.save(out, quality=85)
        return [out]
    dur = probe(path).duration or 1.0
    frames = []
    for i in range(count):
        t = dur * (i + 1) / (count + 1)
        out = out_dir / f"{prefix}{i}.jpg"
        run_ffmpeg("-ss", f"{t:.2f}", "-i", str(path), "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "4", str(out))
        if out.exists():
            frames.append(out)
    return frames


def average_hash(image_path: Path, size: int = 8) -> str:
    """Oddiy perceptual hash - bir xil kadrlarni topish uchun."""
    img = Image.open(image_path).convert("L").resize((size, size))
    pixels = list(img.tobytes())
    avg = sum(pixels) / len(pixels)
    bits = "".join("1" if p > avg else "0" for p in pixels)
    return f"{int(bits, 2):0{size * size // 4}x}"


def hash_distance(a: str, b: str) -> int:
    if not a or not b or len(a) != len(b):
        return 64
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def require_tools() -> None:
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            raise MediaError(f"{tool} topilmadi. O'rnating: Windows - 'winget install --id Gyan.FFmpeg -e'")
