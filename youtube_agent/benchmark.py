"""TTS benchmark: bir xil qiyin o'zbekcha matnni har bir ovozda yaratadi, siz quloq bilan solishtirasiz.

Objektiv signal sifatida: davomiylik, kechikish, narx va (OpenAI kaliti bo'lsa) whisper tanib olgan matnning
asl matnga o'xshashligi - talaffuz xatolari ko'p bo'lsa o'xshashlik pasayadi. Bu quloq bilan eshitishning
o'rnini bosmaydi: yakuniy tanlov sizniki.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from .media import duration
from .speech import prepare_speech
from .subtitles import similarity, transcribe_words
from .tts import BENCHMARK_TEXT, apply_pronunciation, load_pronunciation, make_tts

log = logging.getLogger(__name__)
DEFAULT_VOICES = "openai:marin,openai:cedar,openai:coral,openai:ash,openai:sage,edge:uz-UZ-SardorNeural,edge:uz-UZ-MadinaNeural"


def run_benchmark(out_dir: Path, voices: str, use_asr: bool, tts_model: str, instructions: str,
                  pronunciation_path: Path | None) -> list[dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    text = prepare_speech(apply_pronunciation(BENCHMARK_TEXT, load_pronunciation(pronunciation_path)))
    (out_dir / "benchmark_text.txt").write_text(f"ASL MATN:\n{BENCHMARK_TEXT}\n\nOVOZGA BERILGAN:\n{text}\n", "utf-8")
    results = []
    for item in [v.strip() for v in voices.split(",") if v.strip()]:
        provider, _, voice = item.partition(":")
        row: dict = {"provider": provider, "voice": voice}
        try:
            tts = make_tts(provider, voice, tts_model, instructions)
            res = tts.synthesize(text, out_dir / f"{provider}_{voice}")
            row.update(file=str(res.path), duration=round(duration(res.path), 2), latency_s=res.latency_s,
                       cost_usd=res.cost_usd, word_timestamps=bool(res.words))
            if use_asr:
                asr_text, _ = transcribe_words(res.path, "uz", "")
                row.update(asr_text=asr_text, asr_similarity=round(similarity(text, asr_text), 3))
        except Exception as e:
            row["error"] = str(e)[:300]
        results.append(row)
        log.info("%s", row)
    (out_dir / "report.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), "utf-8")
    return results
