"""Asosiy agent: jadval, Telegram orqali tasdiqlash, video yuklash va kommentlarga javob."""

from __future__ import annotations

import logging
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from .analytics import ChannelDB, snapshot_all, summary
from .config import Config
from .content import draft_comment_reply
from .factory import build_llm, build_pipeline
from .jobs import Job
from .media import extract_frames
from .orchestrator import summarize_job
from .publishing import can_publish, publish
from .schemas import JobState
from .state import State
from .telegram import TelegramBot
from .youtube import YouTube

log = logging.getLogger(__name__)
DAY_NAMES = ["Dushanba", "Seshanba", "Chorshanba", "Payshanba", "Juma", "Shanba", "Yakshanba"]


class Agent:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.state = State(cfg.data_dir / "state.json")
        self.bot = TelegramBot(cfg.telegram_token, cfg.telegram_chat_id)
        self.llm = build_llm(cfg)
        self.pipeline = build_pipeline(cfg, self.llm)
        self.db = ChannelDB(cfg.db_path)
        self.youtube = YouTube(cfg.youtube_token_file)
        self.jobs = ThreadPoolExecutor(max_workers=1)  # og'ir ishlar navbat bilan

    # ------------------------------------------------------------------ jadval
    def now(self) -> datetime:
        return datetime.now(self.cfg.timezone)

    def upcoming_slots(self, count: int = 4) -> list[datetime]:
        now, slots = self.now(), []
        for d in range(15):
            day = (now + timedelta(days=d)).date()
            if day.weekday() not in self.cfg.publish_days:
                continue
            slot = datetime(day.year, day.month, day.day, self.cfg.publish_hour, self.cfg.publish_minute,
                            tzinfo=self.cfg.timezone)
            if slot > now:
                slots.append(slot)
            if len(slots) >= count:
                break
        return slots

    def check_schedule(self) -> None:
        slots = self.upcoming_slots(1)
        if not slots:
            return
        slot = slots[0]
        key = slot.isoformat()
        if self.now() >= slot - timedelta(hours=self.cfg.prepare_hours_before) and key not in self.state["prepared_slots"]:
            self.state["prepared_slots"] = [*self.state["prepared_slots"][-50:], key]
            self.submit(self.prepare_video, slot)

    def submit(self, fn, *args) -> None:
        def run():
            try:
                fn(*args)
            except Exception as e:
                log.exception("Xato: %s", fn.__name__)
                self.bot.send(f"⚠️ Xatolik ({fn.__name__}): {e}\n\n{traceback.format_exc()[-1500:]}")
        self.jobs.submit(run)

    # ------------------------------------------------------------------ video
    def next_category(self) -> str:
        idx = self.state["topic_index"]
        self.state["topic_index"] = idx + 1
        return self.cfg.topics[idx % len(self.cfg.topics)]

    def prepare_video(self, slot: datetime | None, category: str | None = None) -> None:
        category = category or self.next_category()
        when = f"{DAY_NAMES[slot.weekday()]} {slot:%H:%M}" if slot else "darhol"
        self.bot.send(f"🔎 «{category}» bo'yicha yangi Shorts tayyorlanmoqda ({when} uchun). "
                      "Tadqiqot, fakt-tekshiruv, montaj va sifat nazorati 5-15 daqiqa oladi...")
        job = self.pipeline.new_job(category, slot=slot.isoformat() if slot else None)
        self.pipeline.run(job, self.state["published_titles"], summary(self.db))
        self._offer(job, slot, category, when)

    def _offer(self, job: Job, slot: datetime | None, category: str, when: str) -> None:
        """Tayyor (yoki ko'rib chiqish kerak bo'lgan) videoni egasiga Telegram'da yuboradi."""
        pid = uuid.uuid4().hex[:8]
        report = summarize_job(job)
        video = job.path("render/video.mp4")
        review = job.state == JobState.needs_review
        allowed, reason = can_publish(job, owner_override=True)
        if job.state == JobState.approved:
            head, rows = "🎬 Yangi Shorts tayyor va sifat nazoratidan o'tdi!", [
                [("✅ Ha, joylash", f"v:ok:{pid}"), ("❌ Yo'q", f"v:no:{pid}")],
                [("🔄 Boshqa video yarat", f"v:new:{pid}")]]
        elif review and allowed:
            head, rows = "🟡 Video sifat nazoratidan to'liq o'tmadi - o'zingiz ko'rib chiqing.", [
                [("✅ Ko'rdim, baribir joylash", f"v:ok:{pid}"), ("❌ Yo'q", f"v:no:{pid}")],
                [("🔄 Boshqa video yarat", f"v:new:{pid}")]]
        else:
            head, rows = f"🔴 Bu videoni nashr qilib bo'lmaydi: {reason}", [
                [("🔄 Boshqa video yarat", f"v:new:{pid}"), ("❌ Bekor qilish", f"v:no:{pid}")]]
        self.state.update_pending(pid, kind="video", job_id=job.id, category=category, review=review,
                                  slot=slot.isoformat() if slot else None)
        caption = f"{head}\n\n{report}\n⏰ Joylash: {when} ({self.cfg.youtube_privacy})"
        if video.exists():
            thumb = extract_frames(video, job.path("render"), count=1, width=720, prefix="thumb")[0]
            self.bot.send_video(video, caption, self.bot.buttons(rows), thumb)
        else:
            self.bot.send(caption, self.bot.buttons(rows))

    def upload_video(self, pid: str) -> None:
        item = self.state["pending"].get(pid)
        if not item:
            return
        job = Job.load(self.cfg.jobs_dir, item["job_id"])
        slot = datetime.fromisoformat(item["slot"]) if item.get("slot") else None
        title = job.read_json("plan.json")["title"]
        self.bot.send(f"⬆️ «{title}» YouTube'ga yuklanmoqda ({self.cfg.youtube_privacy})...")
        result = publish(job, self.youtube, self.db, self.cfg.youtube_category_id, self.cfg.youtube_privacy,
                         slot, owner_override=bool(item.get("review")))
        self.state["published_titles"] = [*self.state["published_titles"][-200:], title]
        self.state.pop_pending(pid)
        st = result["youtube_status"]
        self.bot.send(f"✅ Yuklandi: {result['url']}\nHolat: {st.get('privacyStatus')} / {st.get('uploadStatus')}"
                      + (f"\nOchilish vaqti: {st.get('publishAt')}" if st.get("publishAt") else ""))

    # --------------------------------------------------------------- kommentlar
    def check_comments(self) -> None:
        since = datetime.now(timezone.utc) - timedelta(days=self.cfg.comment_lookback_days)
        asked = {p.get("thread_id") for p in self.state["pending"].values()}
        for c in self.youtube.recent_comments(since):
            if c["thread_id"] in self.state["seen_comments"] or c["thread_id"] in asked:
                continue
            title = self.youtube.video_title(c["video_id"])
            draft = draft_comment_reply(self.llm, title, c["text"], c["author"])
            if not draft.should_reply:
                self.state.mark_comment_seen(c["thread_id"])
                log.info("Komment o'tkazib yuborildi (%s): %s", draft.reason, c["text"][:80])
                continue
            pid = uuid.uuid4().hex[:8]
            self.state.update_pending(pid, kind="comment", thread_id=c["thread_id"], reply=draft.reply,
                                      text=c["text"], author=c["author"], title=title)
            self.bot.send(
                f"💬 Yangi komment\n🎬 {title}\n👤 {c['author']}:\n«{c['text'][:1500]}»\n\n"
                f"🤖 Taklif qilingan javob:\n«{draft.reply}»\n\nJavob yozilsinmi?",
                self.bot.buttons([
                    [("✅ Javob berish", f"c:ok:{pid}"), ("✏️ O'zim yozaman", f"c:edit:{pid}")],
                    [("❌ O'tkazib yuborish", f"c:skip:{pid}")],
                ]),
            )
        self.state["last_comment_check"] = datetime.now(timezone.utc).isoformat()

    def post_reply(self, pid: str, text: str) -> None:
        item = self.state.pop_pending(pid)
        if not item:
            return
        self.youtube.reply(item["thread_id"], text)
        self.state.mark_comment_seen(item["thread_id"])
        self.bot.send(f"✅ {item['author']} ga javob yozildi.")

    def comments_due(self) -> bool:
        last = self.state["last_comment_check"]
        if not last:
            return True
        return datetime.now(timezone.utc) - datetime.fromisoformat(last) >= timedelta(minutes=self.cfg.comment_check_minutes)

    # ----------------------------------------------------------------- telegram
    def is_owner(self, chat_id) -> bool:
        return str(chat_id) == str(self.cfg.telegram_chat_id)

    def handle_update(self, upd: dict) -> None:
        if "callback_query" in upd:
            cq = upd["callback_query"]
            if not self.is_owner(cq["message"]["chat"]["id"]):
                return self.bot.answer_callback(cq["id"], "Ruxsat yo'q")
            self.handle_callback(cq)
        elif "message" in upd:
            msg = upd["message"]
            chat_id = msg["chat"]["id"]
            if not self.is_owner(chat_id):
                self.bot.send(f"Sizning chat ID: {chat_id}\n.env faylida TELEGRAM_CHAT_ID ga yozing.", chat_id=chat_id)
                return
            self.handle_message(msg.get("text", ""))

    def handle_callback(self, cq: dict) -> None:
        kind, action, pid = (cq.get("data", "").split(":") + ["", "", ""])[:3]
        item = self.state["pending"].get(pid)
        if not item:
            self.bot.answer_callback(cq["id"], "Bu so'rov eskirgan")
            return self.bot.remove_buttons(cq["message"], "ℹ️ Bu so'rov allaqachon hal qilingan.")
        self.bot.answer_callback(cq["id"])
        if kind == "v":
            if action == "ok":
                self.bot.remove_buttons(cq["message"], "👍 Tasdiqlandi, yuklanmoqda.")
                self.state.update_pending(pid, status="approved")
                self.submit(self.upload_video, pid)
            elif action == "no":
                self.bot.remove_buttons(cq["message"], "🚫 Bekor qilindi. Bu video joylanmaydi (fayllari saqlanadi).")
                self.state.pop_pending(pid)
                self._reject(item["job_id"])
            elif action == "new":
                self.bot.remove_buttons(cq["message"], "🔄 Yangi video tayyorlanadi.")
                self.state.pop_pending(pid)
                self._reject(item["job_id"])
                slot = datetime.fromisoformat(item["slot"]) if item.get("slot") else None
                self.submit(self.prepare_video, slot, item["category"])
        elif kind == "c":
            if action == "ok":
                self.bot.remove_buttons(cq["message"], "👍 Javob yuborilmoqda.")
                self.submit(self.post_reply, pid, item["reply"])
            elif action == "edit":
                self.state["awaiting_edit"] = pid
                self.bot.remove_buttons(cq["message"], "✏️ Javob matnini yozib yuboring (bekor qilish: /cancel).")
            elif action == "skip":
                self.bot.remove_buttons(cq["message"], "⏭ O'tkazib yuborildi.")
                self.state.pop_pending(pid)
                self.state.mark_comment_seen(item["thread_id"])

    def _reject(self, job_id: str) -> None:
        try:
            job = Job.load(self.cfg.jobs_dir, job_id)
            if job.state != JobState.published:
                job.set_state(JobState.rejected, "egasi Telegram'da rad etdi")
        except FileNotFoundError:
            pass

    def update_analytics(self) -> None:
        n = snapshot_all(self.db, self.youtube.creds)
        self.bot.send(f"📈 {n} ta video statistikasi yangilandi.\n\n{summary(self.db) or 'Hali yetarli maʼlumot yoʻq.'}")

    def handle_message(self, text: str) -> None:
        text = text.strip()
        editing = self.state["awaiting_edit"]
        if text == "/cancel":
            self.state["awaiting_edit"] = None
            return self.bot.send("Bekor qilindi.")
        if editing and text and not text.startswith("/"):
            self.state["awaiting_edit"] = None
            return self.submit(self.post_reply, editing, text)
        if text in ("/start", "/help"):
            self.bot.send(
                "🤖 YouTube agent ishlayapti.\n\n"
                "/status - jadval va kutilayotgan so'rovlar\n"
                "/video - hoziroq yangi video tayyorlash\n"
                "/comments - kommentlarni hozir tekshirish\n"
                "/jobs - oxirgi ishlar va ularning holati\n"
                "/analytics - YouTube statistikasini yangilash\n"
                "/cancel - tahrirni bekor qilish"
            )
        elif text == "/status":
            slots = "\n".join(f"• {DAY_NAMES[s.weekday()]} {s:%d.%m %H:%M}" for s in self.upcoming_slots())
            pending = self.state["pending"].values()
            videos = sum(1 for p in pending if p["kind"] == "video")
            comments = sum(1 for p in pending if p["kind"] == "comment")
            self.bot.send(f"📅 Keyingi joylashlar:\n{slots}\n\n⏳ Kutilmoqda: {videos} video, {comments} komment")
        elif text == "/video":
            self.submit(self.prepare_video, None)
        elif text == "/comments":
            self.submit(self.check_comments)
        elif text == "/jobs":
            ids = Job.list_ids(self.cfg.jobs_dir)[-8:]
            lines = [f"• {i}: {Job.load(self.cfg.jobs_dir, i).state.value}" for i in ids]
            self.bot.send("\n".join(lines) or "Hali ish yo'q.")
        elif text == "/analytics":
            self.submit(self.update_analytics)

    # -------------------------------------------------------------------- loop
    def run(self) -> None:
        log.info("Agent ishga tushdi. Kanal: %s", self.youtube.channel_id)
        if self.cfg.telegram_chat_id:
            self.bot.send("🟢 Agent ishga tushdi. /help - buyruqlar.")
        else:
            log.warning("TELEGRAM_CHAT_ID yo'q: botga /start yozing va ID'ni .env ga qo'shing")
        while True:
            try:
                for upd in self.bot.get_updates(timeout=25):
                    self.handle_update(upd)
                self.check_schedule()
                if self.comments_due():
                    self.state["last_comment_check"] = datetime.now(timezone.utc).isoformat()
                    self.submit(self.check_comments)
            except KeyboardInterrupt:
                raise
            except Exception:
                log.exception("Asosiy siklda xato")
                time.sleep(10)
