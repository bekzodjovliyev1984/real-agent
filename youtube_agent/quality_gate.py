"""K. Sifat nazorati: tayyor videoni o'zi tekshiriladi (faqat rejaga qarab emas).

A. Deterministik: fayl, oqimlar, o'lcham, davomiylik, FPS, A/V sinxronligi, qora va qotib qolgan kadrlar,
   ovoz balandligi (LUFS), clipping, uzun jimlik, subtitr fayli, aktivlar, litsenziyalar, tasdiqlanmagan da'volar.
B. Mazmuniy: tayyor video'dan har sahna o'rtasidagi kadr olinadi va AI ko'zi bilan baholanadi.

Ballar ichki signal, sifat kafolati emas. Tasdiqlanmagan ilmiy da'vo bo'lsa, ball qancha bo'lishidan qat'i
nazar video nashr qilinmaydi.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .audio_processing import measure
from .categories import render_prompt
from .llm import LLM
from .media import MediaError, probe, run_ffmpeg, run_ffmpeg_analysis
from .schemas import (MAX_DURATION, MIN_DURATION, AssetMeta, NarrationResult, QAReport, QAScores,
                      SemanticReviewDraft, ShortPlan)
from .subtitles import parse_ass_events

log = logging.getLogger(__name__)


@dataclass
class QASettings:
    min_scores: dict[str, float] = field(default_factory=lambda: {
        "storytelling": 6.0, "visual_relevance": 7.0, "audio_quality": 7.0,
        "subtitle_quality": 6.0, "technical_quality": 7.0})
    target_lufs: float = -14.0
    lufs_tolerance: float = 2.5
    max_true_peak: float = -0.5
    min_asr_similarity: float = 0.75
    require_semantic: bool = True


def _stream_durations(path: Path) -> tuple[float, float]:
    res = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", str(path)],
                         capture_output=True, text=True, timeout=60)
    v = a = 0.0
    for s in json.loads(res.stdout or "{}").get("streams", []):
        d = float(s.get("duration") or 0)
        if s.get("codec_type") == "video":
            v = d
        elif s.get("codec_type") == "audio":
            a = d
    return v, a


def technical_check(video: Path, plan: ShortPlan | None, narration: NarrationResult | None,
                    assets: list[AssetMeta], ass_path: Path | None, s: QASettings) -> QAReport:
    r = QAReport()
    try:
        info = probe(video)
    except MediaError as e:
        r.technical_errors.append(str(e))
        return r
    r.metrics.update(duration=round(info.duration, 2), width=info.width, height=info.height, fps=round(info.fps, 2),
                     vcodec=info.vcodec, acodec=info.acodec, pix_fmt=info.pix_fmt, size_mb=round(info.size_bytes / 1e6, 2))
    if not info.has_video:
        r.technical_errors.append("video oqimi yo'q")
    if not info.has_audio:
        r.technical_errors.append("audio oqimi yo'q")
    if info.has_video:
        if info.width < 720 or info.height < 1280:
            r.technical_errors.append(f"o'lcham juda kichik: {info.width}x{info.height} (kamida 720x1280)")
        if info.height and abs(info.width / info.height - 9 / 16) > 0.01:
            r.technical_errors.append(f"nisbat 9:16 emas: {info.width}x{info.height}")
        if info.vcodec != "h264":
            r.technical_errors.append(f"video kodek {info.vcodec}, H.264 kerak")
        if info.pix_fmt != "yuv420p":
            r.technical_errors.append(f"pixel format {info.pix_fmt}, yuv420p kerak")
        if not 29.0 <= info.fps <= 31.0:
            r.technical_errors.append(f"FPS {info.fps:.2f}, 30 kerak")
    if info.has_audio and info.acodec != "aac":
        r.technical_errors.append(f"audio kodek {info.acodec}, AAC kerak")
    if not MIN_DURATION <= info.duration <= MAX_DURATION:
        r.technical_errors.append(f"davomiylik {info.duration:.1f}s - {MIN_DURATION:.0f}-{MAX_DURATION:.0f}s oralig'ida bo'lishi kerak")
    if info.has_video and info.has_audio:
        v, a = _stream_durations(video)
        r.metrics.update(video_stream=round(v, 2), audio_stream=round(a, 2))
        if v and a and abs(v - a) > 0.25:
            r.technical_errors.append(f"ovoz va video uzunligi farq qiladi: video {v:.2f}s, audio {a:.2f}s")
    if info.has_video:
        out = run_ffmpeg_analysis("-i", str(video), "-vf", "blackdetect=d=0.25:pix_th=0.10", "-an")
        blacks = [(float(a), float(b)) for a, b in re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", out)]
        if blacks:
            r.technical_errors.append(f"qora kadrlar: {[(round(a, 2), round(b, 2)) for a, b in blacks][:5]}")
        out = run_ffmpeg_analysis("-i", str(video), "-vf", "freezedetect=n=0.002:d=3", "-an")
        freezes = re.findall(r"freeze_start: ([\d.]+)", out)
        if freezes:
            r.technical_errors.append(f"3s dan uzun qotib qolgan kadr: {freezes[:5]}")
    if info.has_audio:
        am = measure(video)
        r.metrics.update(lufs=am.integrated_lufs, true_peak=am.true_peak_db, peak_db=am.peak_db,
                         long_silences=am.long_silences)
        if am.integrated_lufs is None:
            r.audio_issues.append("ovoz balandligini o'lchab bo'lmadi (ovoz yo'q?)")
        elif abs(am.integrated_lufs - s.target_lufs) > s.lufs_tolerance:
            r.audio_issues.append(f"ovoz balandligi {am.integrated_lufs:.1f} LUFS (maqsad {s.target_lufs})")
        if am.clipped or (am.true_peak_db is not None and am.true_peak_db > s.max_true_peak):
            r.audio_issues.append(f"clipping xavfi: true peak {am.true_peak_db} dBTP")
        if am.long_silences:
            r.audio_issues.append(f"uzun jimlik (sun'iy to'xtash): {am.long_silences[:3]}")
    if narration:
        r.metrics.update(timing_source=narration.timing_source, asr_similarity=narration.asr_similarity,
                         tts=f"{narration.provider}:{narration.voice}")
        if narration.timing_source == "estimated":
            r.subtitle_issues.append("subtitr vaqtlari taxminiy (ovozga moslanmagan)")
        if narration.asr_similarity is not None and narration.asr_similarity < s.min_asr_similarity:
            r.audio_issues.append(f"ovozni tanib olingan matn ssenariydan farq qiladi (o'xshashlik "
                                  f"{narration.asr_similarity:.2f}) - talaffuz xatosi bo'lishi mumkin")
    if ass_path is None or not ass_path.exists():
        r.technical_errors.append("subtitr fayli yo'q")
    else:
        events = parse_ass_events(ass_path.read_text("utf-8"))
        r.metrics["subtitle_events"] = len(events)
        if not events:
            r.technical_errors.append("subtitr faylida birorta ham qator yo'q")
        for st, en, txt in events:
            if en > info.duration + 0.3 or st < 0:
                r.subtitle_issues.append(f"subtitr video tashqarisida: {st:.2f}-{en:.2f}")
                break
        long_lines = [t for _, _, t in events if len(t) > 32]
        if long_lines:
            r.subtitle_issues.append(f"juda uzun subtitr qatorlari: {long_lines[:2]}")
        if any(en - st > 6 for st, en, _ in events):
            r.subtitle_issues.append("6 soniyadan uzun ko'rinadigan subtitr bor")
        bad_chars = [t for _, _, t in events if re.search(r"\b[oOgG]['`´]", t)]
        if bad_chars:
            r.subtitle_issues.append(f"oʻ/gʻ noto'g'ri belgi bilan: {bad_chars[:2]}")
    if plan:
        r.factual_errors += plan.publication_blockers()
        by_scene = {a.scene_id: a for a in assets}
        for sc in plan.scenes:
            a = by_scene.get(sc.id)
            if a is None or not Path(a.local_path).exists():
                r.technical_errors.append(f"sahna {sc.id}: tasdiqlangan vizual aktiv yo'q")
            elif not a.license_verified:
                r.license_warnings.append(f"sahna {sc.id}: {a.provider} rasmi - foydalanish huquqi tekshirilmagan")
        kinds = [a.media_type for a in assets]
        r.metrics["asset_types"] = {k: kinds.count(k) for k in set(kinds)}
        if len({a.fingerprint for a in assets if a.fingerprint}) < len([a for a in assets if a.fingerprint]):
            r.visual_mismatch_issues.append("bir xil kadr bir necha sahnada takrorlangan")
    return r


def extract_review_frames(video: Path, bounds: list[float], out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    for i in range(len(bounds) - 1):
        t = (bounds[i] + bounds[i + 1]) / 2
        f = out_dir / f"scene_{i + 1:02d}.jpg"
        run_ffmpeg("-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1", "-vf", "scale=432:-2", "-q:v", "4", str(f))
        frames.append(f)
    return frames


def semantic_review(llm: LLM, video: Path, plan: ShortPlan, bounds: list[float], work: Path) -> SemanticReviewDraft:
    frames = extract_review_frames(video, bounds, work / "qa_frames")
    scenes = "\n".join(f"{s.id}. [{bounds[s.id - 1]:.1f}-{bounds[s.id]:.1f}s] diktor: \"{s.voiceover_text}\" | "
                       f"kerakli kadr: {s.visual_description}" for s in plan.scenes)
    claims = "\n".join(f"- {c.id} [{c.status.value}] {c.claim}" for c in plan.claims)
    return llm.parse(render_prompt("quality", scenes=scenes, claims=claims), SemanticReviewDraft,
                     effort="medium", images=frames)


def decide(report: QAReport, review: SemanticReviewDraft | None, s: QASettings, attempt: int) -> QAReport:
    r = report
    r.attempt = attempt
    tech = max(0.0, 10.0 - 3.0 * len(r.technical_errors))
    audio = 10.0 - 2.5 * len(r.audio_issues)
    sim = r.metrics.get("asr_similarity")
    if sim is not None:
        audio = min(audio, round(10 * min(1.0, sim / 0.95), 1))
    subtitle_penalty = 3.0 * len(r.subtitle_issues)
    if review:
        r.factual_errors += review.factual_errors
        r.visual_mismatch_issues += review.visual_mismatch_issues
        r.subtitle_issues += review.subtitle_issues
        r.scene_ids_to_fix = sorted(set(review.scene_ids_to_fix))
        r.recommended_fixes += review.recommended_fixes
        r.notes.append(f"AI tekshiruvchi: {review.summary}")
        r.scores = QAScores(storytelling=review.storytelling, visual_relevance=review.visual_relevance,
                            subtitle_quality=max(0.0, min(review.subtitle_quality, 10 - subtitle_penalty)),
                            audio_quality=max(0.0, audio), technical_quality=tech)
    else:
        r.notes.append("mazmuniy (AI) tekshiruv o'tkazilmadi - avtomatik tasdiqlab bo'lmaydi")
        r.scores = QAScores(audio_quality=max(0.0, audio), technical_quality=tech,
                            subtitle_quality=max(0.0, 10 - subtitle_penalty))
    r.notes.append("audio_quality - o'lchovlar va nutqni tanish asosidagi taxmin; quloq bilan eshitishning o'rnini bosmaydi")
    low = {k: v for k, v in r.scores.model_dump().items() if v < s.min_scores.get(k, 0)}
    blocking = bool(r.technical_errors or r.factual_errors or low or (review is None and s.require_semantic))
    r.approved = not blocking
    if r.approved:
        r.route_to = "none"
    elif r.factual_errors or r.technical_errors:
        r.route_to = "human"
    elif "visual_relevance" in low or r.scene_ids_to_fix:
        r.route_to = "visuals"
    elif "audio_quality" in low:
        r.route_to = "audio"
    elif "subtitle_quality" in low:
        r.route_to = "subtitles"
    elif "storytelling" in low:
        r.route_to = "script"
    else:
        r.route_to = "human"
    return r
