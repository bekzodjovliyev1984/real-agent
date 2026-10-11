"""Telegram agenti: tayyor video taklifi, tugmalar, nashr va kommentlar (soxta servislar bilan)."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock

from youtube_agent import agent as agent_mod
from youtube_agent.agent import Agent
from youtube_agent.analytics import ChannelDB
from youtube_agent.config import Config
from youtube_agent.content import CommentReply
from youtube_agent.jobs import Job
from youtube_agent.schemas import JobState, QAReport
from youtube_agent.state import State


def _agent(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    cfg = Config.from_env()
    a = Agent.__new__(Agent)
    a.cfg, a.state = cfg, State(tmp_path / "state.json")
    a.bot = MagicMock()
    a.bot.buttons = lambda rows: rows
    a.youtube = MagicMock()
    a.youtube.upload.return_value = "VID1"
    a.youtube.video_status.return_value = {"privacyStatus": "private", "uploadStatus": "uploaded"}
    a.db = ChannelDB(tmp_path / "db.sqlite")
    a.llm = MagicMock()
    calls = []
    a.submit = lambda fn, *args: (calls.append(fn.__name__), fn(*args))
    return a, calls


def _approved_job(cfg, state=JobState.approved, report=None):
    job = Job.create(cfg.jobs_dir, "Ilm-fan")
    job.path("render/video.mp4").write_bytes(b"x")
    job.write("qa_report.json", report or QAReport(approved=True))
    job.write("plan.json", {"title": "Test #shorts", "description": "d", "tags": [], "category": "Ilm-fan",
                            "hook_type": "question", "scenes": [1, 2, 3]})
    job.meta["state"] = state.value
    job.save()
    return job


def test_schedule_triggers_once(tmp_path, monkeypatch):
    a, calls = _agent(tmp_path, monkeypatch)
    a.submit = lambda fn, *args: calls.append(fn.__name__)
    slot = a.upcoming_slots(1)[0]
    a.now = lambda: slot - timedelta(hours=2)
    a.check_schedule()
    a.check_schedule()
    assert calls == ["prepare_video"]


def test_offer_and_publish_flow(tmp_path, monkeypatch):
    a, calls = _agent(tmp_path, monkeypatch)
    monkeypatch.setattr(agent_mod, "extract_frames", lambda *x, **k: [tmp_path / "t.jpg"])
    job = _approved_job(a.cfg)
    a._offer(job, None, "Ilm-fan", "darhol")
    pid, item = next(iter(a.state["pending"].items()))
    assert item["job_id"] == job.id
    rows = a.bot.send_video.call_args.args[2]
    assert rows[0][0][1] == f"v:ok:{pid}"
    a.handle_update({"callback_query": {"id": "c", "data": f"v:ok:{pid}", "message": {"chat": {"id": 42}, "message_id": 1}}})
    assert "upload_video" in calls
    assert Job.load(a.cfg.jobs_dir, job.id).state == JobState.published
    assert a.youtube.upload.call_args.args[-1] == "private"


def test_blocked_job_has_no_publish_button(tmp_path, monkeypatch):
    a, _ = _agent(tmp_path, monkeypatch)
    monkeypatch.setattr(agent_mod, "extract_frames", lambda *x, **k: [tmp_path / "t.jpg"])
    job = _approved_job(a.cfg, JobState.needs_review, QAReport(factual_errors=["tasdiqlanmagan"]))
    a._offer(job, None, "Ilm-fan", "darhol")
    rows = a.bot.send_video.call_args.args[2]
    assert all(not b[1].startswith("v:ok") for row in rows for b in row)


def test_comment_reply_needs_owner_approval(tmp_path, monkeypatch):
    a, calls = _agent(tmp_path, monkeypatch)
    a.youtube.recent_comments.return_value = [{"thread_id": "T1", "video_id": "V", "author": "Ali", "text": "Zo'r!"}]
    a.youtube.video_title.return_value = "Video"
    monkeypatch.setattr(agent_mod, "draft_comment_reply",
                        lambda llm, t, c, au: CommentReply(should_reply=True, reply="Rahmat!", reason=""))
    a.check_comments()
    a.youtube.reply.assert_not_called()  # ruxsatsiz javob yozilmaydi
    pid = next(iter(a.state["pending"]))
    a.handle_update({"callback_query": {"id": "c", "data": f"c:ok:{pid}", "message": {"chat": {"id": 42}, "message_id": 1}}})
    a.youtube.reply.assert_called_once_with("T1", "Rahmat!")
    a.handle_update({"message": {"chat": {"id": 99}, "text": "/video"}})  # begona odam
    assert "prepare_video" not in calls
