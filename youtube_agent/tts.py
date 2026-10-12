"""G. O'zbekcha ovoz (TTS) adapterlari va benchmark.

Provayderlar bir xil interfeysga ega, shuning uchun .env'da TTS_PROVIDER/TTS_VOICE ni almashtirish yetarli:
- openai: gpt-4o-mini-tts (ovoz uslubi `instructions` bilan boshqariladi; so'z vaqtlarini qaytarmaydi -
  subtitrlar uchun keyin whisper bilan moslanadi)
- edge:   Microsoft Edge neural ovozlari (bepul; so'z vaqtlarini o'zi qaytaradi)

Matn butun hikoya bo'yicha BIR MARTA o'qitiladi (har sahna alohida emas) - ohang uzilmaydi.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from .media import duration, run_ffmpeg
from .schemas import WordTiming

log = logging.getLogger(__name__)
RESOURCES = Path(__file__).parent / "resources"

DEFAULT_INSTRUCTIONS = (
    "Language: Uzbek (Latin script). Voice: a warm, knowledgeable Uzbek documentary storyteller explaining "
    "something fascinating to a friend. Natural conversational intonation, clear articulation, moderate pace, "
    "brief natural pauses at commas and full stops. Pronounce Uzbek sounds correctly: oʻ, gʻ, q (deep back k), "
    "x (like German ch), h, and the glottal stop ʼ. Questions rise in pitch naturally. No exaggerated drama, "
    "no monotone, no English or Russian accent."
)

BENCHMARK_TEXT = (
    "Bilasizmi, nega osmon koʻk rangda koʻrinadi? Quyosh nuri havodagi molekulalarga urilib, qisqa toʻlqinli "
    "koʻk nurni har tomonga sochadi va bu hodisa Reley sochilishi deb ataladi. 2025-yilda olimlar yangi kvant "
    "kompyuterini sinovdan oʻtkazishdi: u 5 daqiqada hal qilgan masalani oddiy superkompyuter 10 000 yilda "
    "yechar edi. Gʻalati tuyuladimi? Qargʻalar esa oyna oldida oʻzini taniy oladi, xuddi odamlar kabi. "
    "Endi eng qiziq savol: sunʼiy intellekt haqiqatan oʻylaydimi yoki faqat keyingi soʻzni bashorat qiladimi? "
    "OpenAI va Google DeepMind bu savolga turlicha javob beradi."
)


@dataclass
class TTSResult:
    path: Path
    words: list[WordTiming] = field(default_factory=list)  # bo'sh bo'lsa - keyin moslash kerak
    provider: str = ""
    voice: str = ""
    model: str = ""
    cost_usd: float = 0.0
    latency_s: float = 0.0


class TTSProvider(Protocol):
    name: str
    voice: str

    def synthesize(self, text: str, out: Path) -> TTSResult: ...


# ------------------------------------------------------------ talaffuz lug'ati
def load_pronunciation(extra_path: Path | None = None) -> dict[str, str]:
    data = json.loads((RESOURCES / "pronunciation.json").read_text("utf-8"))
    if extra_path and extra_path.exists():
        data.update(json.loads(extra_path.read_text("utf-8")))
    return {k: v for k, v in data.items() if not k.startswith("_")}


def apply_pronunciation(text: str, mapping: dict[str, str]) -> str:
    # uzunroq kalitlar birinchi (masalan "ChatGPT" "GPT"dan oldin)
    for key in sorted(mapping, key=len, reverse=True):
        text = re.sub(rf"(?<![\w]){re.escape(key)}(?![\w])", mapping[key], text)
    return text


def split_for_tts(text: str, limit: int = 3500) -> list[str]:
    """Juda uzun matnni gap chegaralari bo'yicha bo'ladi (OpenAI kirish chegarasi ~4096 belgi)."""
    if len(text) <= limit:
        return [text]
    parts, cur = [], ""
    for sent in re.split(r"(?<=[.!?])\s+", text):
        if cur and len(cur) + len(sent) + 1 > limit:
            parts.append(cur)
            cur = sent
        else:
            cur = f"{cur} {sent}".strip()
    if cur:
        parts.append(cur)
    return parts


# ------------------------------------------------------------------ provayderlar
class OpenAITTS:
    name = "openai"

    def __init__(self, voice: str = "marin", model: str = "gpt-4o-mini-tts", instructions: str = DEFAULT_INSTRUCTIONS,
                 speed: float = 1.0, price_per_minute: float = 0.015):
        from openai import OpenAI

        self.client = OpenAI()
        self.voice, self.model, self.instructions, self.speed = voice, model, instructions, speed
        self.price_per_minute = price_per_minute

    def synthesize(self, text: str, out: Path) -> TTSResult:
        started = time.time()
        parts = split_for_tts(text)
        files = []
        for i, part in enumerate(parts):
            p = out.with_name(f"{out.stem}_part{i}.wav") if len(parts) > 1 else out.with_suffix(".wav")
            kwargs = {"model": self.model, "voice": self.voice, "input": part, "response_format": "wav"}
            if self.model.startswith("gpt-4o"):
                kwargs["instructions"] = self.instructions
            if self.speed != 1.0:
                kwargs["speed"] = self.speed
            with self.client.audio.speech.with_streaming_response.create(**kwargs) as resp:
                resp.stream_to_file(p)
            files.append(p)
        final = out.with_suffix(".wav")
        if len(files) > 1:
            lst = out.with_name("tts_parts.txt")
            lst.write_text("".join(f"file '{f.name}'\n" for f in files), encoding="utf-8")
            run_ffmpeg("-f", "concat", "-safe", "0", "-i", lst.name, "-c", "copy", final.name, cwd=out.parent)
        dur = duration(final)
        return TTSResult(final, [], self.name, self.voice, self.model,
                         round(dur / 60 * self.price_per_minute, 4), round(time.time() - started, 2))


class EdgeTTS:
    name = "edge"

    def __init__(self, voice: str = "uz-UZ-SardorNeural", rate: str = "+0%"):
        self.voice, self.rate = voice, rate

    async def _run(self, text: str, out: Path) -> list[WordTiming]:
        import edge_tts

        comm = edge_tts.Communicate(text, self.voice, rate=self.rate, boundary="WordBoundary")
        words: list[WordTiming] = []
        with open(out, "wb") as f:
            async for chunk in comm.stream():
                if chunk["type"] == "audio":
                    f.write(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    start = chunk["offset"] / 1e7
                    words.append(WordTiming(text=chunk["text"], start=start, end=start + chunk["duration"] / 1e7))
        return words

    def synthesize(self, text: str, out: Path) -> TTSResult:
        from .jobs import retry

        started = time.time()
        out = out.with_suffix(".mp3")
        # Microsoft serveri ba'zan vaqtincha 403 qaytaradi - bir necha marta qayta urinamiz
        words = retry(lambda: asyncio.run(self._run(text, out)), attempts=4, base_delay=3, what="Edge TTS")
        return TTSResult(out, words, self.name, self.voice, "edge-neural", 0.0, round(time.time() - started, 2))


def make_tts(provider: str, voice: str, model: str = "", instructions: str = "", rate: str = "+0%",
             price_per_minute: float = 0.015) -> TTSProvider:
    provider = provider.lower()
    if provider == "openai":
        return OpenAITTS(voice=voice or "marin", model=model or "gpt-4o-mini-tts",
                         instructions=instructions or DEFAULT_INSTRUCTIONS, price_per_minute=price_per_minute)
    if provider == "edge":
        return EdgeTTS(voice=voice or "uz-UZ-SardorNeural", rate=rate)
    raise ValueError(f"Noma'lum TTS_PROVIDER: {provider} (openai yoki edge)")
