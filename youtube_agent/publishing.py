"""L. Nashr: faqat sifat nazoratidan o'tgan (yoki egasi ko'rib chiqib, bloklovchi xatosi yo'q) videolar yuklanadi."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from .analytics import ChannelDB, record_publication
from .jobs import Job
from .schemas import JobState, QAReport, utcnow

log = logging.getLogger(__name__)


class PublishBlocked(RuntimeError):
    pass


def can_publish(job: Job, owner_override: bool = False) -> tuple[bool, str]:
    """approved - ha. needs_review - faqat egasi tasdiqlasa VA fakt/texnik xato bo'lmasa. Boshqa holatlar - yo'q."""
    if job.state == JobState.published:
        return False, "allaqachon nashr qilingan"
    if not job.has("render/video.mp4") or not job.has("qa_report.json"):
        return False, "video yoki QA hisobot yo'q"
    report = QAReport.model_validate_json(job.path("qa_report.json").read_text("utf-8"))
    if report.factual_errors:
        return False, "tasdiqlanmagan/xato ilmiy da'volar bor: " + "; ".join(report.factual_errors[:2])
    if report.technical_errors:
        return False, "texnik xatolar bor: " + "; ".join(report.technical_errors[:2])
    if job.state == JobState.approved:
        return True, "QA tasdiqlagan"
    if job.state == JobState.needs_review and owner_override:
        return True, "egasi ko'rib chiqib tasdiqladi"
    return False, f"holat {job.state.value} - nashr qilib bo'lmaydi"


def publish(job: Job, youtube, db: ChannelDB, category_id: str, privacy: str = "private",
            publish_at: datetime | None = None, owner_override: bool = False) -> dict:
    ok, reason = can_publish(job, owner_override)
    if not ok:
        raise PublishBlocked(reason)
    plan = job.read_json("plan.json")
    log.info("[%s] YouTube'ga yuklanmoqda (%s): %s", job.id, privacy, reason)
    video_id = youtube.upload(Path(job.path("render/video.mp4")), None, plan["title"], plan["description"],
                              plan.get("tags", []), category_id, publish_at, privacy)
    status = youtube.video_status(video_id)
    result = {"video_id": video_id, "url": f"https://youtu.be/{video_id}", "privacy": privacy,
              "publish_at": publish_at.isoformat() if publish_at else None, "uploaded_at": utcnow(),
              "reason": reason, "youtube_status": status}
    job.write("publish.json", result)
    job.set_state(JobState.published, f"{video_id} ({privacy})")
    record_publication(db, job, video_id, privacy)
    return result
