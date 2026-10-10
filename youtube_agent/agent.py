"""Asosiy agent: jadval, Telegram orqali tasdiqlash, video yuklash va kommentlarga javob."""

from __future__ import annotations

import logging
import shutil
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import Config
from .content import VideoPlan, make_creator
from .state import State
from .telegram import TelegramBot
from .video import VideoMaker
from .youtube import YouTube

log = logging.getLogger(__name__)
DAY_NAMES = ["Dushanba", "Seshanba", "Chorshanba", "Payshanba", "Juma", "Shanba", "Yakshanba"]


class Agent:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.state = State(cfg.data_dir / "state.json")
        self.bot = TelegramBot(cfg.telegram_token, cfg.telegram_chat_id)
        self.creator = make_creator(cfg.llm_provider, cfg.llm_model, cfg.video_language)
        self.maker = VideoMaker(cfg.shorts_settings())
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
        self.bot.send(f"🔎 «{category}» bo'yicha yangi video tayyorlanmoqda ({when} uchun)...")
        plan = self.creator.create_video_plan(category, self.state["published_titles"])
        pid = uuid.uuid4().hex[:8]
        workdir = self.cfg.data_dir / "videos" / pid
        video, thumb = self.maker.build(plan, category, workdir)
        self.state.update_pending(pid, kind="video", status="waiting", category=category,
                                  slot=slot.isoformat() if slot else None, plan=plan.model_dump(),
                                  video=str(video), thumb=str(thumb))
        caption = (
            f"🎬 Yangi Shorts tayyor!\n\n📌 {plan.title}\n🗂 {category}\n⏰ Joylash vaqti: {when}\n\n"
            f"{plan.description[:600]}\n\nVideo qo'yilsinmi?"
        )
        buttons = self.bot.buttons([
            [("✅ Ha, joylash", f"v:ok:{pid}"), ("❌ Yo'q", f"v:no:{pid}")],
            [("🔄 Boshqa video yarat", f"v:new:{pid}")],
        ])
        self.bot.send_video(video, caption, buttons, thumb)

    def upload_video(self, pid: str) -> None:
        item = self.state["pending"].get(pid)
        if not item:
            return
        plan = VideoPlan.model_validate(item["plan"])
        slot = datetime.fromisoformat(item["slot"]) if item.get("slot") else None
        self.bot.send(f"⬆️ «{plan.title}» YouTube'ga yuklanmoqda...")
        video_id = self.youtube.upload(
            video=Path(item["video"]), thumb=None,  # Shorts muqovasini YouTube o'zi tanlaydi
            title=plan.title, description=plan.description, tags=plan.tags,
            category_id=self.cfg.youtube_category_id, publish_at=slot,
        )
        self.state["published_titles"] = [*self.state["published_titles"][-200:], plan.title]
        self.state.pop_pending(pid)
        shutil.rmtree(Path(item["video"]).parent, ignore_errors=True)
        when = f"{slot:%d.%m %H:%M} da avtomatik ochiladi" if slot and slot > self.now() else "hozir ochiq"
        self.bot.send(f"✅ Yuklandi ({when}):\nhttps://youtu.be/{video_id}")

    # --------------------------------------------------------------- kommentlar
    def check_comments(self) -> None:
        since = datetime.now(timezone.utc) - timedelta(days=self.cfg.comment_lookback_days)
        asked = {p.get("thread_id") for p in self.state["pending"].values()}
        for c in self.youtube.recent_comments(since):
            if c["thread_id"] in self.state["seen_comments"] or c["thread_id"] in asked:
                continue
            title = self.youtube.video_title(c["video_id"])
            draft = self.creator.draft_comment_reply(title, c["text"], c["author"])
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
                self.bot.remove_buttons(cq["message"], "🚫 Bekor qilindi. Bu video joylanmaydi.")
                self.state.pop_pending(pid)
                shutil.rmtree(Path(item["video"]).parent, ignore_errors=True)
            elif action == "new":
                self.bot.remove_buttons(cq["message"], "🔄 Yangi video tayyorlanadi.")
                self.state.pop_pending(pid)
                shutil.rmtree(Path(item["video"]).parent, ignore_errors=True)
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
