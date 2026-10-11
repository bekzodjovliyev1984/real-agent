"""Butun ishlab chiqarish quvuri: mavzu -> fakt-tekshiruv -> ssenariy -> storyboard -> vizuallar -> ovoz
-> subtitrlar -> montaj -> sifat nazorati.

Har bosqich natijasi ish papkasiga yoziladi. Dastur to'xtab qolsa, `resume` bilan tugagan bosqichlar
qayta bajarilmaydi. Vizual topilmasa ssenariy va ovoz qayta yaratilmaydi - faqat o'sha sahna qidiriladi.
Sifat nazoratidan o'tmasa: ko'pi bilan 2 marta avtomatik tuzatish, keyin `needs_review`.
"""

from __future__ import annotations

import logging
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .audio_processing import LEAD_IN, TAIL, mix_final, pick_music, process_narration
from .fact_checker import verify_claims
from .jobs import Job, retry
from .llm import LLM
from .media import duration as media_duration
from .pricing import WHISPER_PER_MINUTE, llm_cost
from .quality_gate import QASettings, decide, semantic_review, technical_check
from .render import RenderSettings, assemble, finalize, render_scene, scene_durations
from .schemas import (PUBLISHABLE_STATUSES, AssetMeta, Claim, JobState, NarrationResult, QAReport, ScriptDraft,
                      ShortPlan, TopicDraft, WordTiming)
from .script_agent import write_script
from .speech import prepare_speech
from .storyboard_agent import build_storyboard
from .subtitles import (SubtitleStyle, align, build_ass, chunk, display_words, estimate, norm_token,
                        scene_bounds, similarity, tokens, transcribe_words)
from .topic_agent import research_topic
from .tts import TTSProvider, apply_pronunciation, load_pronunciation
from .visual_search import VisualSearcher

log = logging.getLogger(__name__)


@dataclass
class PipelineSettings:
    jobs_dir: Path
    render: RenderSettings
    min_seconds: float = 25.0
    max_seconds: float = 55.0
    max_corrections: int = 2
    ai_video_enabled: bool = False
    music_dir: Path | None = None
    music_db: float = -22.0
    sfx_dir: Path | None = None
    target_lufs: float = -14.0
    true_peak: float = -1.5
    use_asr: bool = True
    pronunciation_path: Path | None = None
    subtitle_style: SubtitleStyle = field(default_factory=SubtitleStyle)
    qa: QASettings = field(default_factory=QASettings)


class PipelineError(RuntimeError):
    pass


class Pipeline:
    def __init__(self, settings: PipelineSettings, llm: LLM | None, tts: TTSProvider,
                 searcher_factory: Callable[[], VisualSearcher],
                 transcriber: Callable[[Path, str], tuple[str, list[WordTiming]]] | None = None):
        self.s = settings
        self.llm = llm
        self.tts = tts
        self.searcher_factory = searcher_factory
        self.transcriber = transcriber if transcriber is not None else (
            (lambda p, prompt: transcribe_words(p, "uz", prompt)) if settings.use_asr else None)
        self.pron = load_pronunciation(settings.pronunciation_path)

    # ------------------------------------------------------------------ boshqaruv
    def new_job(self, category: str, **extra) -> Job:
        return Job.create(self.s.jobs_dir, category, extra)

    def run(self, job: Job, avoid_titles: list[str] | None = None, performance: str = "") -> Job:
        """Ishni to'xtagan joyidan oxirigacha (approved yoki needs_review) olib boradi."""
        job.attach_log()
        usage_start = len(self.llm.usage) if self.llm else 0
        try:
            if job.state in (JobState.approved, JobState.needs_review, JobState.published, JobState.rejected):
                return job
            self._research(job, avoid_titles or [], performance)
            if job.state == JobState.needs_review:
                return job
            self._script(job)
            if job.state == JobState.needs_review:
                return job
            while True:
                self._assets(job)
                self._audio(job)
                self._subtitles(job)
                self._render(job)
                report = self._qa(job)
                if report.approved:
                    job.set_state(JobState.approved, "sifat nazoratidan o'tdi")
                    break
                if not self._correct(job, report):
                    job.set_state(JobState.needs_review, f"tuzatib bo'lmadi: {report.route_to}")
                    break
            return job
        except Exception as e:
            job.record_error(job.state.value, f"{e}\n{traceback.format_exc()[-1500:]}")
            raise
        finally:
            if self.llm:
                costs = job.meta.setdefault("costs", {})
                costs["llm"] = round(costs.get("llm", 0) + llm_cost(self.llm.usage[usage_start:]), 4)
                costs["total"] = round(sum(v for k, v in costs.items() if k != "total"), 4)
                job.save()
            job.detach_log()

    # ------------------------------------------------------------------ bosqichlar
    def _research(self, job: Job, avoid: list[str], performance: str) -> None:
        if job.has("claims.json"):
            return
        avoid = list(avoid)
        for attempt in range(1, 3):
            topic, text = research_topic(self.llm, job.meta["category"], avoid, performance)
            claims, evidence = verify_claims(self.llm, topic.claims)
            usable = [c for c in claims if c.status in PUBLISHABLE_STATUSES]
            job.write(f"research_{attempt}.json", {"topic": topic.model_dump(), "research_text": text,
                                                   "fact_check_text": evidence})
            if len(usable) >= 3:
                job.write("research.json", {"topic": topic.model_dump(), "research_text": text,
                                            "fact_check_text": evidence})
                job.write("claims.json", [c.model_dump() for c in claims])
                job.set_state(JobState.researched, f"{topic.topic}: {len(usable)}/{len(claims)} da'vo tasdiqlandi")
                return
            log.warning("'%s' mavzusida tasdiqlangan da'volar kam (%d) - boshqa mavzu qidiriladi", topic.topic, len(usable))
            avoid.append(topic.topic)
        job.set_state(JobState.needs_review, "ikki urinishda ham yetarli tasdiqlangan fakt topilmadi")

    def _load_claims(self, job: Job) -> list[Claim]:
        return [Claim.model_validate(c) for c in job.read_json("claims.json")]

    def _script(self, job: Job) -> None:
        if job.has("plan.json"):
            return
        topic = TopicDraft.model_validate(job.read_json("research.json")["topic"])
        claims = self._load_claims(job)
        if job.has("script.json"):
            script = job.read_model("script.json", ScriptDraft)
        else:
            script = write_script(self.llm, job.meta["category"], topic, claims, self.s.min_seconds, self.s.max_seconds)
            job.write("script.json", script)
        plan = build_storyboard(self.llm, job.meta["category"], topic, script, claims, self.s.ai_video_enabled)
        job.write("plan.json", plan)
        blockers = plan.publication_blockers()
        if blockers:
            job.set_state(JobState.needs_review, "; ".join(blockers)[:500])
            return
        job.set_state(JobState.scripted, f"{len(plan.scenes)} sahna")

    def plan(self, job: Job) -> ShortPlan:
        return job.read_model("plan.json", ShortPlan)

    def assets(self, job: Job) -> list[AssetMeta]:
        return [AssetMeta.model_validate(a) for a in job.read_json("assets.json")] if job.has("assets.json") else []

    def _assets(self, job: Job) -> None:
        plan = self.plan(job)
        have = {a.scene_id: a for a in self.assets(job)}
        if all(s.id in have for s in plan.scenes):
            return
        searcher = self.searcher_factory()
        # boshqa sahnalardagi kadrlar takrorlanmasin
        for a in have.values():
            searcher.used_keys.add(f"{a.provider}:{a.asset_id}")
            if a.fingerprint:
                searcher.used_hashes.append(a.fingerprint)
        rejected = set(job.meta.get("rejected_assets", []))
        sources = [s.url for c in plan.claims for s in c.sources]
        logs = job.read_json("assets_log.json") if job.has("assets_log.json") else {}
        for sc in plan.scenes:
            if sc.id in have:
                continue
            asset, slog = searcher.find(sc, job.path(f"assets/scene_{sc.id:02d}"), sources, palette=sc.id,
                                        skip_keys=rejected, fallback_title=plan.topic[:40])
            have[sc.id] = asset
            logs[str(sc.id)] = slog.tried
            log.info("Sahna %d: %s (%s) %s", sc.id, asset.provider, asset.media_type,
                     f"ball={asset.relevance_score}" if asset.relevance_score is not None else "")
            job.write("assets.json", [have[k].model_dump() for k in sorted(have)])  # har sahnadan keyin saqlanadi
            job.write("assets_log.json", logs)
        job.meta.setdefault("costs", {})["ai_video"] = round(sum(a.cost_usd for a in have.values()), 4)
        job.set_state(JobState.assets_ready, ", ".join(f"{k}:{have[k].media_type}" for k in sorted(have)))

    def _audio(self, job: Job) -> None:
        if job.has("narration.json"):
            return
        plan = self.plan(job)
        speech = [prepare_speech(apply_pronunciation(s.voiceover_text, self.pron)) for s in plan.scenes]
        full = " ".join(speech)
        raw = retry(lambda: self.tts.synthesize(full, job.path("audio/raw")), attempts=3, what="TTS")
        processed = job.path("audio/narration.wav")
        shift, metrics = process_narration(raw.path, processed, self.s.target_lufs, self.s.true_peak)
        total = media_duration(processed)
        toks = tokens(full)
        result = NarrationResult(provider=raw.provider, voice=raw.voice, model=raw.model, raw_audio=str(raw.path),
                                 processed_audio=str(processed), duration=total, speech_text=full,
                                 loudness_lufs=metrics.integrated_lufs, true_peak_db=metrics.true_peak_db,
                                 cost_usd=raw.cost_usd)
        asr_text, asr_words = "", []
        if self.transcriber:
            try:
                asr_text, asr_words = self.transcriber(processed, full)
                result.asr_text = asr_text
                result.asr_similarity = round(similarity(full, asr_text), 3)
                job.meta.setdefault("costs", {})["whisper"] = round(total / 60 * WHISPER_PER_MINUTE, 4)
            except Exception as e:
                log.warning("Nutqni tanib olish (whisper) ishlamadi: %s", e)
        if raw.words:
            shifted = [WordTiming(text=w.text, start=max(0, w.start + shift), end=max(0, w.end + shift)) for w in raw.words]
            result.words, result.timing_source = align(toks, shifted, total), "tts"
        elif asr_words:
            result.words, result.timing_source = align(toks, asr_words, total), "alignment"
        else:
            result.words, result.timing_source = estimate(toks, LEAD_IN, total - TAIL), "estimated"
        counts = [len(tokens(s)) for s in speech]
        result.scene_bounds = scene_bounds(counts, result.words, total)
        # musiqa va effektlar
        music = pick_music(self.s.music_dir, plan.music_mood) if self.s.music_dir else None
        sfx = []
        if self.s.sfx_dir:
            for i, sc in enumerate(plan.scenes):
                f = self.s.sfx_dir / f"{sc.sound_effect}.mp3"
                if sc.sound_effect != "none" and f.exists():
                    sfx.append((result.scene_bounds[i], f))
        mix_final(processed, job.path("audio/final_mix.wav"), total, music, self.s.music_db, sfx)
        job.write("narration.json", result)
        job.meta.setdefault("costs", {})["tts"] = result.cost_usd
        job.set_state(JobState.audio_ready, f"{result.provider}:{result.voice}, {total:.1f}s, vaqt: {result.timing_source}")

    def narration(self, job: Job) -> NarrationResult:
        return job.read_model("narration.json", NarrationResult)

    def _subtitles(self, job: Job) -> None:
        if job.has("captions.ass"):
            return
        plan, nar = self.plan(job), self.narration(job)
        speech = [prepare_speech(apply_pronunciation(s.voiceover_text, self.pron)) for s in plan.scenes]
        per_scene, i = [], 0
        for s in speech:
            n = len(tokens(s))
            per_scene.append(nar.words[i:i + n])
            i += n
        emph = [{norm_token(t) for t in tokens(s.on_screen_text)} for s in plan.scenes]
        words = display_words([s.subtitle_text for s in plan.scenes], per_scene, emph)
        chunks = chunk(words)
        job.write("subtitles.json", [[w.__dict__ for w in c] for c in chunks])
        job.path("captions.ass").write_text(build_ass(chunks, self.s.subtitle_style, nar.duration), encoding="utf-8")

    def _render(self, job: Job) -> None:
        out = job.path("render/video.mp4")
        if out.exists():
            return
        plan, nar = self.plan(job), self.narration(job)
        assets = {a.scene_id: a for a in self.assets(job)}
        bounds = nar.scene_bounds
        durs = scene_durations(bounds, plan.scenes)
        clips = []
        for sc, dur in zip(plan.scenes, durs):
            clip = job.path(f"render/scene_{sc.id:02d}.mp4")
            if not clip.exists():
                render_scene(assets[sc.id], sc, dur, clip, self.s.render)
            clips.append(clip)
        joined = assemble(clips, plan.scenes, bounds, job.path("render/joined.mp4"))
        finalize(joined, job.path("audio/final_mix.wav"), job.path("captions.ass"), nar.duration, out, self.s.render,
                 [self.s.render.font_bold, self.s.render.font_regular])
        job.set_state(JobState.rendered, f"{media_duration(out):.1f}s")

    def _qa(self, job: Job) -> QAReport:
        plan, nar = self.plan(job), self.narration(job)
        video = job.path("render/video.mp4")
        report = technical_check(video, plan, nar, self.assets(job), job.path("captions.ass"), self.s.qa)
        review = None
        if self.llm:
            try:
                review = semantic_review(self.llm, video, plan, nar.scene_bounds, job.root)
            except Exception as e:
                report.notes.append(f"AI tekshiruv xatosi: {e}")
        attempt = int(job.meta.get("attempt", 1))
        report = decide(report, review, self.s.qa, attempt)
        job.write(f"qa_report_{attempt}.json", report)
        job.write("qa_report.json", report)
        log.info("QA: approved=%s ballar=%s yo'nalish=%s", report.approved, report.scores.model_dump(), report.route_to)
        return report

    # ------------------------------------------------------------------ tuzatish
    def _correct(self, job: Job, report: QAReport) -> bool:
        attempt = int(job.meta.get("attempt", 1))
        if attempt > self.s.max_corrections or report.route_to in ("human", "none"):
            return False
        job.meta["attempt"] = attempt + 1
        job.set_state(JobState.qa_failed, f"{attempt}-urinish: {report.route_to} qayta ishlanadi")
        render_files = [f"render/{p.name}" for p in job.path("render").glob("*.mp4")]
        if report.route_to == "visuals":
            ids = set(report.scene_ids_to_fix)
            if not ids:
                return False
            keep = []
            for a in self.assets(job):
                if a.scene_id in ids:
                    job.meta.setdefault("rejected_assets", []).append(f"{a.provider}:{a.asset_id}")
                else:
                    keep.append(a.model_dump())
            job.write("assets.json", keep)
            job.save()
            job.invalidate(*render_files)
        elif report.route_to == "audio":
            job.invalidate("narration.json", "captions.ass", "subtitles.json", *render_files)
        elif report.route_to == "subtitles":
            job.invalidate("captions.ass", "subtitles.json", "render/video.mp4")
        elif report.route_to == "script":
            job.invalidate("script.json", "plan.json", "assets.json", "narration.json", "captions.ass",
                           "subtitles.json", *render_files)
            self._script(job)
            return job.state != JobState.needs_review
        return True


def summarize_job(job: Job) -> str:
    """Telegram uchun qisqa hisobot."""
    lines = [f"🆔 {job.id} — {job.state.value}"]
    if job.has("plan.json"):
        plan = job.read_json("plan.json")
        lines.append(f"📌 {plan['title']}\n🗂 {plan['category']} · {len(plan['scenes'])} sahna")
    if job.has("qa_report.json"):
        r = job.read_json("qa_report.json")
        sc = r["scores"]
        lines.append("📊 " + ", ".join(f"{k}={v:g}" for k, v in sc.items()))
        for key, title in (("technical_errors", "Texnik"), ("factual_errors", "Fakt"), ("audio_issues", "Ovoz"),
                           ("visual_mismatch_issues", "Kadr"), ("subtitle_issues", "Subtitr"),
                           ("license_warnings", "Litsenziya")):
            if r.get(key):
                lines.append(f"⚠️ {title}: " + "; ".join(r[key][:3]))
    costs = job.meta.get("costs", {})
    if costs:
        lines.append(f"💵 ~${costs.get('total', 0):.2f} (taxminiy)")
    return "\n".join(lines)
