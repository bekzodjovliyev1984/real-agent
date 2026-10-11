"""H. Ovozni qayta ishlash: boshi/oxiridagi jimlikni kesish (ichki pauzalar saqlanadi), ovoz balandligini
LUFS bo'yicha tekislash, o'lchovlar (LUFS, true peak, clipping, uzun jimlik), musiqa va effektlarni aralashtirish.

O'lchovlar sifat nazorati uchun signal, xolos - ular quloq bilan eshitib ko'rishning o'rnini bosmaydi.
"""

from __future__ import annotations

import json
import logging
import random
import re
from dataclasses import dataclass, field
from pathlib import Path

from .media import duration, run_ffmpeg, run_ffmpeg_analysis

log = logging.getLogger(__name__)
SAMPLE_RATE = 48000
LEAD_IN = 0.15   # boshida qoldiriladigan sukunat
TAIL = 0.6       # oxirida (abrupt tugashning oldini oladi)


@dataclass
class AudioMetrics:
    integrated_lufs: float | None = None
    true_peak_db: float | None = None
    peak_db: float | None = None
    clipped: bool = False
    long_silences: list[tuple[float, float]] = field(default_factory=list)
    duration: float = 0.0


def leading_silence(path: Path, threshold_db: float = -50) -> float:
    out = run_ffmpeg_analysis("-i", str(path), "-af", f"silencedetect=noise={threshold_db}dB:d=0.05")
    m = re.search(r"silence_start: (-?[\d.]+)\s.*?silence_end: ([\d.]+)", out, re.S)
    if m and float(m.group(1)) <= 0.01:
        return float(m.group(2))
    return 0.0


def measure(path: Path, silence_db: float = -45, min_silence: float = 1.2) -> AudioMetrics:
    m = AudioMetrics(duration=duration(path))
    out = run_ffmpeg_analysis("-i", str(path), "-af", "loudnorm=print_format=json")
    j = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", out, re.S)
    if j:
        data = json.loads(j.group(0))
        m.integrated_lufs = float(data["input_i"]) if data["input_i"] not in ("-inf", "inf") else None
        m.true_peak_db = float(data["input_tp"]) if data["input_tp"] not in ("-inf", "inf") else None
    out = run_ffmpeg_analysis("-i", str(path), "-af", "astats=measure_overall=Peak_level:measure_perchannel=none")
    p = re.search(r"Peak level dB:\s*(-?[\d.]+|-inf)", out)
    if p and p.group(1) != "-inf":
        m.peak_db = float(p.group(1))
        m.clipped = m.peak_db >= -0.05
    out = run_ffmpeg_analysis("-i", str(path), "-af", f"silencedetect=noise={silence_db}dB:d={min_silence}")
    for s, e in re.findall(r"silence_start: ([\d.]+).*?silence_end: ([\d.]+)", out, re.S):
        s, e = float(s), float(e)
        if s > 0.5 and e < m.duration - 0.8:  # boshi va oxiridagi jimlik hisobga olinmaydi
            m.long_silences.append((round(s, 2), round(e - s, 2)))
    return m


def process_narration(raw: Path, out: Path, target_lufs: float = -14.0, true_peak: float = -1.5) -> tuple[float, AudioMetrics]:
    """Qayta ishlangan ovozni yozadi. Qaytaradi: (vaqt siljishi = yangi_vaqt - eski_vaqt, o'lchovlar)."""
    lead = leading_silence(raw)
    trimmed = out.with_name("narration_trimmed.wav")
    # boshidagi va oxiridagi jimlik kesiladi; gaplar orasidagi tabiiy pauzalarga tegilmaydi
    trim = ("silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.05,"
            "areverse,silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.1,areverse,"
            "highpass=f=70")
    run_ffmpeg("-i", str(raw), "-af", trim, "-ar", str(SAMPLE_RATE), "-ac", "1", str(trimmed))
    # ikki bosqichli loudnorm: avval o'lchaymiz, keyin chiziqli tekislaymiz (kompressiyasiz)
    first = run_ffmpeg_analysis("-i", str(trimmed), "-af",
                                f"loudnorm=I={target_lufs}:TP={true_peak}:LRA=11:print_format=json")
    j = json.loads(re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", first, re.S).group(0))
    norm = (f"loudnorm=I={target_lufs}:TP={true_peak}:LRA=11:measured_I={j['input_i']}:measured_TP={j['input_tp']}:"
            f"measured_LRA={j['input_lra']}:measured_thresh={j['input_thresh']}:offset={j['target_offset']}:linear=true")
    pad = f"adelay={int(LEAD_IN * 1000)}:all=1,apad=pad_dur={TAIL}"
    run_ffmpeg("-i", str(trimmed), "-af", f"{norm},{pad}", "-ar", str(SAMPLE_RATE), "-ac", "1", str(out))
    trimmed.unlink(missing_ok=True)
    shift = LEAD_IN + 0.05 - lead  # silenceremove boshida 0.05s qoldiradi
    return shift, measure(out)


def pick_music(music_dir: Path, mood: str) -> Path | None:
    """music/<kayfiyat>/*.mp3 dan, bo'lmasa music/*.mp3 dan tasodifiy trek (mualliflik huquqi sizning javobgarligingizda)."""
    if not music_dir.is_dir() or mood == "none":
        return None
    files = sorted((music_dir / mood).glob("*.mp3")) if (music_dir / mood).is_dir() else []
    files = files or sorted(music_dir.glob("*.mp3"))
    return random.Random(mood).choice(files) if files else None


def mix_final(narration: Path, out: Path, total: float, music: Path | None = None, music_db: float = -22.0,
              sfx: list[tuple[float, Path]] | None = None) -> None:
    """Diktor + (ixtiyoriy) musiqa ovoz kelganda pasayadi (sidechain) + (ixtiyoriy) effektlar."""
    inputs = ["-i", str(narration)]
    parts = ["[0:a]aformat=sample_rates=48000:channel_layouts=stereo,asplit=2[voice][key]"]
    mix = ["[voice]"]
    idx = 1
    if music:
        inputs += ["-stream_loop", "-1", "-i", str(music)]
        parts.append(f"[{idx}:a]aformat=sample_rates=48000:channel_layouts=stereo,volume={music_db}dB,"
                     f"afade=t=in:d=1,afade=t=out:st={max(total - 1.5, 0):.2f}:d=1.5[mraw]")
        parts.append("[mraw][key]sidechaincompress=threshold=0.03:ratio=6:attack=20:release=400[music]")
        mix.append("[music]")
        idx += 1
    else:
        parts.append("[key]anullsink")
    for t, path in sfx or []:
        inputs += ["-i", str(path)]
        parts.append(f"[{idx}:a]aformat=sample_rates=48000:channel_layouts=stereo,volume=-10dB,"
                     f"adelay={int(t * 1000)}:all=1[s{idx}]")
        mix.append(f"[s{idx}]")
        idx += 1
    if len(mix) > 1:
        parts.append(f"{''.join(mix)}amix=inputs={len(mix)}:duration=first:normalize=0,alimiter=limit=0.89[out]")
    else:
        parts.append("[voice]alimiter=limit=0.89[out]")
    run_ffmpeg(*inputs, "-filter_complex", ";".join(parts), "-map", "[out]", "-t", f"{total:.3f}",
               "-ar", str(SAMPLE_RATE), "-c:a", "pcm_s16le", str(out))
