"""I. Subtitrlar: haqiqiy ovozga sinxron, o'qilishi oson ASS subtitrlar.

Vaqt manbalari (afzallik tartibida):
1. TTS o'zi qaytargan so'z vaqtlari (Edge);
2. Tayyor ovozni whisper bilan tanib, tasdiqlangan matnga moslash (forced alignment o'rniga);
3. Hech biri bo'lmasa - taxminiy vaqt (QA buni muammo deb belgilaydi va nashrni to'xtatadi).

Ekranda toza imloli subtitle_text ko'rsatiladi; ovozga ketgan (raqamlari so'z bilan yozilgan) matn alohida
saqlanadi va ekranda ko'rinmaydi.
"""

from __future__ import annotations

import difflib
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from .schemas import WordTiming

log = logging.getLogger(__name__)
TOKEN_RE = re.compile(r"[^\W_]+(?:[ʻʼ‘’'`-][^\W_]+)*")


def tokens(text: str) -> list[str]:
    return TOKEN_RE.findall(text)


def norm_token(t: str) -> str:
    return re.sub(r"[ʻʼ‘’'`\-]", "", t.lower())


# ------------------------------------------------------------- tanib olish
def transcribe_words(audio: Path, language: str = "uz", prompt: str = "") -> tuple[str, list[WordTiming]]:
    """OpenAI whisper-1: so'zma-so'z vaqtlar bilan transkripsiya.
    API 'uz' til kodini qabul qilmaydi, shuning uchun til avtomatik aniqlanadi; matn esa ishora (prompt) sifatida beriladi."""
    from openai import OpenAI

    with open(audio, "rb") as f:
        res = OpenAI().audio.transcriptions.create(
            model="whisper-1", file=f, response_format="verbose_json",
            timestamp_granularities=["word"], prompt=prompt[:800],
        )
    words = [WordTiming(text=w.word, start=w.start, end=w.end) for w in (res.words or [])]
    return res.text, words


def similarity(a: str, b: str) -> float:
    na = " ".join(norm_token(t) for t in tokens(a))
    nb = " ".join(norm_token(t) for t in tokens(b))
    return difflib.SequenceMatcher(None, na, nb).ratio() if na and nb else 0.0


# ----------------------------------------------------------------- moslash
def align(speech_tokens: list[str], asr_words: list[WordTiming], total: float) -> list[WordTiming]:
    """Tasdiqlangan matn so'zlariga tanib olingan so'zlarning vaqtini ko'chiradi.
    Mos kelmagan bo'laklar qo'shni vaqtlar orasida harf soniga qarab taqsimlanadi."""
    n = len(speech_tokens)
    starts: list[float | None] = [None] * n
    ends: list[float | None] = [None] * n
    a = [norm_token(t) for t in speech_tokens]
    b = [norm_token(w.text) for w in asr_words]
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                starts[i1 + k], ends[i1 + k] = asr_words[j1 + k].start, asr_words[j1 + k].end
        elif tag == "replace" and j2 > j1:
            t0, t1 = asr_words[j1].start, asr_words[j2 - 1].end
            _spread(speech_tokens, starts, ends, i1, i2, t0, t1)
    # qolgan bo'shliqlar - qo'shnilar orasida
    i = 0
    while i < n:
        if starts[i] is not None:
            i += 1
            continue
        j = i
        while j < n and starts[j] is None:
            j += 1
        t0 = ends[i - 1] if i > 0 and ends[i - 1] is not None else 0.0
        t1 = starts[j] if j < n and starts[j] is not None else total
        _spread(speech_tokens, starts, ends, i, j, t0, max(t1, t0 + 0.05))
        i = j
    out, prev = [], 0.0
    for tok, s, e in zip(speech_tokens, starts, ends):
        s = max(float(s), prev)
        e = max(float(e), s + 0.04)
        out.append(WordTiming(text=tok, start=round(s, 3), end=round(e, 3)))
        prev = s
    return out


def _spread(toks: list[str], starts: list, ends: list, i1: int, i2: int, t0: float, t1: float) -> None:
    weights = [len(t) + 1 for t in toks[i1:i2]]
    total = sum(weights) or 1
    t = t0
    for k, w in enumerate(weights):
        d = (t1 - t0) * w / total
        starts[i1 + k], ends[i1 + k] = t, t + d
        t += d


def estimate(speech_tokens: list[str], start: float, end: float) -> list[WordTiming]:
    starts: list = [None] * len(speech_tokens)
    ends: list = [None] * len(speech_tokens)
    _spread(speech_tokens, starts, ends, 0, len(speech_tokens), start, end)
    return [WordTiming(text=t, start=s, end=e) for t, s, e in zip(speech_tokens, starts, ends)]


def scene_bounds(scene_token_counts: list[int], words: list[WordTiming], total: float) -> list[float]:
    """Har sahna boshlanish vaqti (+ oxirgi element = umumiy davomiylik)."""
    bounds, idx = [0.0], 0
    for c in scene_token_counts[:-1]:
        idx += c
        t = words[min(idx, len(words) - 1)].start - 0.06 if words else bounds[-1] + total / len(scene_token_counts)
        bounds.append(max(bounds[-1] + 0.6, t))
    bounds.append(total)
    return bounds


# ------------------------------------------------------- ekrandagi subtitrlar
@dataclass
class SubWord:
    text: str
    start: float
    end: float
    emphasis: bool = False
    scene_id: int = 0


def display_words(subtitle_texts: list[str], scene_word_timings: list[list[WordTiming]],
                  emphasis_terms: list[set[str]]) -> list[SubWord]:
    """Ekran matnining har so'ziga vaqt beradi: sahna ichida ovozdagi so'zlar vaqti bo'yicha, harf ulushiga qarab."""
    result: list[SubWord] = []
    for sid, (text, spoken, emph) in enumerate(zip(subtitle_texts, scene_word_timings, emphasis_terms), 1):
        disp = text.split()
        if not disp or not spoken:
            continue
        # ovozdagi so'zlar bo'yicha "harf o'qi" -> vaqt
        cum, marks = 0, []
        for w in spoken:
            marks.append((cum, w.start))
            cum += len(w.text) + 1
        marks.append((cum, spoken[-1].end))
        total_chars = sum(len(t) + 1 for t in disp)

        def at(frac: float) -> float:
            pos = frac * cum
            for (c0, t0), (c1, t1) in zip(marks, marks[1:]):
                if pos <= c1:
                    return t0 + (t1 - t0) * ((pos - c0) / (c1 - c0) if c1 > c0 else 0)
            return marks[-1][1]

        times, c = [], 0
        for t in disp:
            s = at(c / total_chars)
            c += len(t) + 1
            times.append([s, at(c / total_chars)])
        # bir xil so'zlar aniq ovozdagi vaqtini oladi; farq qiladiganlari (masalan "2x" / "ikki baravar")
        # yuqoridagi harf ulushi bo'yicha taxmin qilingan vaqtda qoladi
        d_norm = [norm_token(re.sub(r"[^\w'ʻʼ‘’-]", "", t)) for t in disp]
        s_norm = [norm_token(w.text) for w in spoken]
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, d_norm, s_norm, autojunk=False).get_opcodes():
            if tag == "equal":
                for k in range(i2 - i1):
                    times[i1 + k] = [spoken[j1 + k].start, spoken[j1 + k].end]
            elif tag == "replace":  # "2x" <-> "ikki baravar": ovozdagi bo'lak vaqti bo'ylab taqsimlanadi
                t0, t1 = spoken[j1].start, spoken[j2 - 1].end
                for k in range(i2 - i1):
                    times[i1 + k] = [t0 + (t1 - t0) * k / (i2 - i1), t0 + (t1 - t0) * (k + 1) / (i2 - i1)]
        prev = spoken[0].start
        for t, (s, e), clean in zip(disp, times, d_norm):
            s = max(s, prev)
            prev = s
            result.append(SubWord(t, s, max(e, s + 0.05), any(ch.isdigit() for ch in t) or clean in emph, sid))
    return result


def chunk(words: list[SubWord], max_words: int = 4, max_chars: int = 24) -> list[list[SubWord]]:
    chunks, cur = [], []
    for w in words:
        too_long = cur and (len(" ".join(x.text for x in cur)) + len(w.text) + 1 > max_chars)
        new_scene = cur and cur[-1].scene_id != w.scene_id
        if too_long or new_scene or len(cur) >= max_words:
            chunks.append(cur)
            cur = []
        cur.append(w)
        if re.search(r"[.!?:;]$", w.text) or (re.search(r",$", w.text) and len(cur) >= 2):
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)
    return chunks


def ass_time(t: float) -> str:
    t = max(t, 0)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def ass_escape(text: str) -> str:
    text = text.replace("ʻ", "‘").replace("ʼ", "’")  # har qanday shriftda bor belgilar
    return text.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")


@dataclass
class SubtitleStyle:
    font_name: str = "Arial"
    size: int = 64
    outline: int = 5
    shadow: int = 2
    margin_v: int = 560     # pastdan: Shorts tugmalari va sarlavha qatlamidan yuqorida
    margin_l: int = 110
    margin_r: int = 170     # o'ngdagi like/komment tugmalari uchun joy
    emphasis_bgr: str = "00D7FF"  # sariq (BGR)


def build_ass(chunks: list[list[SubWord]], style: SubtitleStyle, total: float) -> str:
    header = (
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\nWrapStyle: 0\nScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
        "MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Cap,{style.font_name},{style.size},&H00FFFFFF,&H00FFFFFF,&H00101010,&H90000000,-1,0,0,0,100,100,0,0,1,"
        f"{style.outline},{style.shadow},2,{style.margin_l},{style.margin_r},{style.margin_v},1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    lines = [header]
    for i, ch in enumerate(chunks):
        start = ch[0].start
        nxt = chunks[i + 1][0].start if i + 1 < len(chunks) else total
        end = min(max(ch[-1].end + 0.25, start + 0.5), nxt, total)
        parts = [f"{{\\c&H{style.emphasis_bgr}&}}{ass_escape(w.text)}{{\\c&HFFFFFF&}}" if w.emphasis
                 else ass_escape(w.text) for w in ch]
        lines.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Cap,,0,0,0,,"
                     f"{{\\fad(60,40)}}{' '.join(parts)}\n")
    return "".join(lines)


def parse_ass_events(text: str) -> list[tuple[float, float, str]]:
    events = []
    for m in re.finditer(r"^Dialogue: \d+,(\d+):(\d+):([\d.]+),(\d+):(\d+):([\d.]+),[^,]*,[^,]*,\d+,\d+,\d+,[^,]*,(.*)$",
                         text, re.M):
        s = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
        e = int(m.group(4)) * 3600 + int(m.group(5)) * 60 + float(m.group(6))
        events.append((s, e, re.sub(r"\{[^}]*\}", "", m.group(7))))
    return events
