"""Butun quvur: soxta AI/TTS/rasmlar bilan, lekin haqiqiy ffmpeg montaji va haqiqiy sifat nazorati."""

from __future__ import annotations

import json

import pytest

from fakes import FONT, FONT_BOLD, FakeLLM, FakeProviders, FakeSearcher, FakeTTS, make_media
from youtube_agent import fact_checker
from youtube_agent.jobs import Job
from youtube_agent.media import probe
from youtube_agent.orchestrator import Pipeline, PipelineSettings
from youtube_agent.render import RenderSettings
from youtube_agent.schemas import JobState, QAReport
from youtube_agent.visual_search import VisualSettings


@pytest.fixture
def pipeline_factory(tmp_path, monkeypatch):
    monkeypatch.setattr(fact_checker, "check_url", lambda url, client=None: True)  # tarmoqsiz
    media = make_media(tmp_path / "media")

    def make(llm):
        settings = PipelineSettings(jobs_dir=tmp_path / "jobs", render=RenderSettings(FONT_BOLD, FONT, FONT_BOLD, preset="veryfast"),
                                    use_asr=False)
        vs = VisualSettings(vision_check=True, font_bold=FONT_BOLD, font_regular=FONT)
        return Pipeline(settings, llm, FakeTTS(), lambda: FakeSearcher(vs, llm, None, FakeProviders(media)))
    return make


def test_end_to_end_approved(pipeline_factory):
    llm = FakeLLM(review_score=8.5)
    p = pipeline_factory(llm)
    job = p.new_job("Yangi mashinalar")
    p.run(job)
    assert job.state == JobState.approved, job.read_json("qa_report.json")
    info = probe(job.path("render/video.mp4"))
    assert (info.width, info.height) == (1080, 1920)
    assert info.vcodec == "h264" and info.acodec == "aac" and info.pix_fmt == "yuv420p"
    assert 15 <= info.duration <= 60
    plan = json.loads(job.path("plan.json").read_text())
    assets = json.loads(job.path("assets.json").read_text())
    assert len(assets) == len(plan["scenes"]) >= 3
    assert len({(a["provider"], a["asset_id"]) for a in assets}) == len(assets)  # takror yo'q
    assert {a["media_type"] for a in assets} >= {"video"}
    report = QAReport.model_validate_json(job.path("qa_report.json").read_text())
    assert report.approved and not report.technical_errors, report
    for name in ("research.json", "claims.json", "script.json", "narration.json", "subtitles.json", "captions.ass",
                 "assets_log.json", "job.log"):
        assert job.has(name), name
    assert job.meta["costs"]["llm"] > 0


def test_resume_skips_finished_stages(pipeline_factory):
    llm = FakeLLM()
    p = pipeline_factory(llm)
    job = p.new_job("Yangi mashinalar")
    p.run(job)
    calls = len(llm.calls)
    job2 = Job.load(p.s.jobs_dir, job.id)
    job2.meta["state"] = JobState.rendered.value  # "qulab tushgan" ish
    job2.invalidate("qa_report.json")
    p.run(job2)
    assert job2.state == JobState.approved
    new_calls = llm.calls[calls:]
    assert "TopicDraft" not in new_calls and "ScriptDraft" not in new_calls and "research" not in new_calls


def test_low_visual_score_retries_then_needs_review(pipeline_factory):
    llm = FakeLLM(review_score=5.0)  # AI tekshiruvchi doim "kadr mos emas" deydi
    p = pipeline_factory(llm)
    job = p.new_job("Yangi mashinalar")
    p.run(job)
    assert job.state == JobState.needs_review
    assert job.has("qa_report_1.json") and job.has("qa_report_3.json") and not job.has("qa_report_4.json")
    assert job.meta.get("rejected_assets")


def test_budget_cap_stops_before_next_paid_stage(pipeline_factory, monkeypatch):
    monkeypatch.setenv("PRICE_FAKE_MODEL", "100,100")  # har chaqiruv ~$0.11+ bo'ladi
    llm = FakeLLM()
    p = pipeline_factory(llm)
    p.s.max_cost_usd = 0.5
    job = p.new_job("Yangi mashinalar")
    p.run(job)
    assert job.state == JobState.needs_review
    assert "pul chegarasi" in job.meta["history"][-1]["note"]
    assert "ScriptDraft" not in llm.calls  # ssenariy (pullik) boshlanmagan
    assert job.meta["costs"]["llm"] > 0.5
    # resume: tadqiqot qayta to'lanmaydi
    llm.calls.clear()
    job.meta["state"] = JobState.researched.value
    job.save()
    p.s.max_cost_usd = 0
    p.run(job)
    assert "research" not in llm.calls and "TopicDraft" not in llm.calls


def test_relative_jobs_dir_like_windows_cli(pipeline_factory, tmp_path, monkeypatch):
    """Windows'da DATA_DIR=data (nisbiy) bo'lganda montaj 'joined.mp4 topilmadi' xatosi bilan yiqilgan edi."""
    from pathlib import Path
    monkeypatch.chdir(tmp_path)
    p = pipeline_factory(FakeLLM())
    p.s.jobs_dir = Path("data") / "jobs"
    job = p.new_job("Yangi mashinalar")
    p.run(job)
    assert job.state == JobState.approved and job.has("render/video.mp4")
