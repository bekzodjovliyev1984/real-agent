"""Sifat nazorati (ataylab buzilgan videoni rad etish), nashr shartlari, analitika bazasi va Telegram oqimi."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock

import pytest

from youtube_agent.analytics import ChannelDB, summary
from youtube_agent.jobs import Job
from youtube_agent.publishing import PublishBlocked, can_publish, publish
from youtube_agent.quality_gate import QASettings, decide, technical_check
from youtube_agent.schemas import JobState, NarrationResult, QAReport, SemanticReviewDraft


def _ffmpeg(*args):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


@pytest.fixture
def bad_video(tmp_path):
    """Ataylab yaroqsiz: gorizontal, 6 soniya, 2 soniya qora kadr, ovozi juda baland va clipping bor."""
    out = tmp_path / "bad.mp4"
    _ffmpeg("-f", "lavfi", "-i", "color=black:s=1280x720:d=2:r=25", "-f", "lavfi", "-i", "testsrc2=s=1280x720:d=4:r=25",
            "-f", "lavfi", "-i", "sine=f=440:d=6,volume=8",
            "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]", "-map", "[v]", "-map", "2:a",
            "-c:v", "mpeg4", "-c:a", "mp3", str(out))
    return out


@pytest.fixture
def good_video(tmp_path):
    out = tmp_path / "good.mp4"
    _ffmpeg("-f", "lavfi", "-i", "testsrc2=s=1080x1920:d=20:r=30", "-f", "lavfi",
            "-i", "sine=f=330:d=20,volume=0.3", "-af", "loudnorm=I=-14:TP=-1.5", "-c:v", "libx264", "-pix_fmt",
            "yuv420p", "-c:a", "aac", "-ar", "48000", "-shortest", str(out))
    ass = tmp_path / "c.ass"
    ass.write_text("[Events]\nDialogue: 0,0:00:01.00,0:00:02.00,Cap,,0,0,0,,Salom dunyo\n", "utf-8")
    return out, ass


def test_deliberately_invalid_video_is_rejected(bad_video, tmp_path):
    r = technical_check(bad_video, None, None, [], None, QASettings())
    text = " | ".join(r.technical_errors + r.audio_issues)
    for expected in ("nisbat 9:16 emas", "davomiylik", "qora kadrlar", "H.264", "AAC", "subtitr fayli yo'q"):
        assert expected in text, (expected, text)
    review = SemanticReviewDraft(storytelling=9, visual_relevance=9, subtitle_quality=9, factual_errors=[],
                                 visual_mismatch_issues=[], subtitle_issues=[], scene_ids_to_fix=[],
                                 recommended_fixes=[], summary="")
    final = decide(r, review, QASettings(), attempt=1)
    assert not final.approved and final.route_to == "human" and final.scores.technical_quality < 7


def test_good_video_passes_technical_checks(good_video):
    video, ass = good_video
    nar = NarrationResult(provider="x", voice="v", raw_audio="", speech_text="", timing_source="alignment",
                          asr_similarity=0.95)
    r = technical_check(video, None, nar, [], ass, QASettings())
    assert not r.technical_errors, r.technical_errors
    assert not r.audio_issues, r.audio_issues


def test_decide_thresholds_and_routing():
    review = SemanticReviewDraft(storytelling=8, visual_relevance=5, subtitle_quality=8, factual_errors=[],
                                 visual_mismatch_issues=["sahna 2"], subtitle_issues=[], scene_ids_to_fix=[2],
                                 recommended_fixes=[], summary="")
    r = decide(QAReport(metrics={"asr_similarity": 0.93}), review, QASettings(), 1)
    assert not r.approved and r.route_to == "visuals" and r.scene_ids_to_fix == [2]
    r2 = decide(QAReport(factual_errors=["tasdiqlanmagan"]), review.model_copy(update={"visual_relevance": 9}),
                QASettings(), 1)
    assert not r2.approved and r2.route_to == "human"  # tasdiqlanmagan fakt - ball qanday bo'lmasin bloklanadi
    r3 = decide(QAReport(metrics={"asr_similarity": 0.95}), review.model_copy(update={"visual_relevance": 9,
                                                                                       "scene_ids_to_fix": []}),
                QASettings(), 1)
    assert r3.approved
    r4 = decide(QAReport(metrics={"asr_similarity": 0.5}), review.model_copy(update={"visual_relevance": 9,
                                                                                      "scene_ids_to_fix": []}),
                QASettings(), 1)
    assert not r4.approved and r4.route_to == "audio"
    assert not decide(QAReport(), None, QASettings(), 1).approved  # AI tekshiruvisiz avtomatik tasdiq yo'q


def _job(tmp_path, state, report: QAReport):
    job = Job.create(tmp_path / "jobs", "Ilm-fan")
    job.path("render/video.mp4").write_bytes(b"x")
    job.write("qa_report.json", report)
    job.write("plan.json", {"title": "T #shorts", "description": "d", "tags": [], "category": "Ilm-fan",
                            "hook_type": "question", "scenes": []})
    job.meta["state"] = state.value
    job.save()
    return job


def test_publication_requires_approval(tmp_path):
    yt = MagicMock()
    yt.upload.return_value = "VID123"
    yt.video_status.return_value = {"found": True, "privacyStatus": "private", "uploadStatus": "uploaded"}
    db = ChannelDB(tmp_path / "db.sqlite")

    review_job = _job(tmp_path, JobState.needs_review, QAReport())
    assert not can_publish(review_job)[0]
    with pytest.raises(PublishBlocked):
        publish(review_job, yt, db, "28")
    yt.upload.assert_not_called()

    factual = _job(tmp_path, JobState.needs_review, QAReport(factual_errors=["x"]))
    assert not can_publish(factual, owner_override=True)[0]  # egasi ham fakt xatosini chetlab o'ta olmaydi

    ok = _job(tmp_path, JobState.approved, QAReport(approved=True))
    res = publish(ok, yt, db, "28", privacy="private")
    assert res["video_id"] == "VID123" and ok.state == JobState.published and ok.has("publish.json")
    assert yt.upload.call_args.args[-1] == "private"  # sinovda standart - private
    assert db.videos()[0]["video_id"] == "VID123"


def test_analytics_summary_with_nulls(tmp_path):
    db = ChannelDB(tmp_path / "db.sqlite")
    db.record_video({"job_id": "j1", "video_id": "v1", "title": "t", "category": "Ilm-fan", "hook_type": "question",
                     "published_at": "2026-10-01T00:00:00+00:00"})
    db.add_snapshot("v1", 3, {"views": 100, "averageViewPercentage": 70.5})
    db.add_snapshot("v1", 30, {"views": None})  # 7 kunlik oynadan tashqarida
    s = summary(db, window_days=7)
    assert "Ilm-fan" in s and "70.5" in s and "sabab emas" in s
    row = db.latest_metrics(7)[0]
    assert row["viewed_vs_swiped"] is None  # API'da yo'q - o'ylab topilmaydi
