"""Claude yordamida mavzu topish, internetdan ma'lumot yig'ish va ssenariy yozish."""

from __future__ import annotations

import logging

import anthropic
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

FALLBACK_BETA = "server-side-fallback-2026-07-01"
WEB_SEARCH = {"type": "web_search_20260209", "name": "web_search", "max_uses": 8}


class Scene(BaseModel):
    heading: str = Field(description="Ekranda ko'rinadigan qisqa sarlavha (5-8 so'z)")
    bullets: list[str] = Field(description="Ekrandagi 2-4 ta qisqa punkt")
    narration: str = Field(description="Diktor o'qiydigan matn (60-120 so'z)")


class VideoPlan(BaseModel):
    title: str = Field(description="YouTube sarlavhasi, 100 belgidan kam, qiziqarli, lekin clickbait emas")
    description: str = Field(description="YouTube tavsifi: qisqa mazmun, manbalar ro'yxati, hashtaglar")
    tags: list[str] = Field(description="10-15 ta teg")
    thumbnail_text: str = Field(description="Muqova uchun 2-5 so'zlik katta yozuv")
    scenes: list[Scene] = Field(description="6-10 ta sahna: kirish, asosiy qism, xulosa")
    sources: list[str] = Field(description="Foydalanilgan manbalar URL'lari")


class CommentReply(BaseModel):
    should_reply: bool = Field(description="Spam, haqorat yoki javob talab qilmaydigan bo'lsa false")
    reply: str = Field(description="Javob matni (should_reply false bo'lsa bo'sh)")
    reason: str = Field(description="Qisqa izoh: nega shunday qaror qilindi")


class ContentRefused(RuntimeError):
    pass


class ContentCreator:
    def __init__(self, model: str, language: str):
        self.client = anthropic.Anthropic()
        self.model = model
        self.language = language

    def _check(self, resp) -> None:
        if resp.stop_reason == "refusal":
            raise ContentRefused(f"Claude so'rovni rad etdi: {resp.stop_details}")

    def research(self, category: str, avoid_titles: list[str]) -> str:
        """Internetdan izlab, video uchun yangi mavzu va faktlarni yig'adi."""
        avoid = "\n".join(f"- {t}" for t in avoid_titles[-40:]) or "(hali yo'q)"
        prompt = (
            f"Sen ilmiy-ommabop YouTube kanali uchun tadqiqotchisan. Kategoriya: «{category}».\n"
            "Veb-qidiruv orqali shu kategoriyada so'nggi oylardagi eng qiziqarli, ishonchli manbalarga "
            "(ilmiy jurnallar, universitetlar, WHO, NASA, yirik nashrlar) tayangan BITTA mavzuni tanla.\n"
            f"Avval chiqqan videolar (takrorlama):\n{avoid}\n\n"
            "Natija: tanlangan mavzu, nega qiziq, 8-12 ta aniq fakt (raqamlar, sanalar bilan), "
            "har bir faktning manba URL'i. Tibbiyot mavzusida faqat tasdiqlangan ma'lumot ber, "
            "davolash bo'yicha shaxsiy maslahat berma."
        )
        messages: list = [{"role": "user", "content": prompt}]
        for _ in range(5):  # pause_turn bo'lsa davom ettiramiz
            resp = self.client.beta.messages.create(
                model=self.model,
                max_tokens=16000,
                betas=[FALLBACK_BETA],
                fallbacks="default",
                thinking={"type": "adaptive"},
                output_config={"effort": "high"},
                tools=[WEB_SEARCH],
                messages=messages,
            )
            self._check(resp)
            if resp.stop_reason == "pause_turn":
                messages = [*messages, {"role": "assistant", "content": resp.content}]
                continue
            return "\n".join(b.text for b in resp.content if b.type == "text")
        raise RuntimeError("Tadqiqot juda uzoq davom etdi (pause_turn chegarasi)")

    def write_script(self, category: str, research_notes: str) -> VideoPlan:
        prompt = (
            f"Quyidagi tadqiqot asosida {self.language} tilida 4-6 daqiqalik ilmiy-ommabop video ssenariysini yoz. "
            f"Kategoriya: {category}.\n"
            "Talablar: birinchi sahnada kuchli 'hook' (savol yoki hayratlanarli fakt); sodda, jonli til; "
            "faqat tadqiqotdagi faktlardan foydalan; oxirgi sahnada xulosa va obunaga chaqiriq. "
            "Tavsif oxiriga manbalarni va '#shorts' emas, mavzuga oid 3-5 hashtag qo'sh. "
            "Tibbiyot bo'lsa tavsifga 'Bu video ma'lumot uchun, shifokor maslahatining o'rnini bosmaydi' "
            "degan ogohlantirish qo'sh. Raqamlarni diktor o'qishi uchun so'z bilan yozish shart emas.\n\n"
            f"TADQIQOT:\n{research_notes}"
        )
        resp = self.client.beta.messages.parse(
            model=self.model,
            max_tokens=16000,
            betas=[FALLBACK_BETA],
            fallbacks="default",
            thinking={"type": "adaptive"},
            output_config={"effort": "medium"},
            messages=[{"role": "user", "content": prompt}],
            output_format=VideoPlan,
        )
        self._check(resp)
        plan = resp.parsed_output
        plan.title = plan.title[:100]
        plan.description = plan.description[:4900]
        return plan

    def create_video_plan(self, category: str, avoid_titles: list[str]) -> VideoPlan:
        log.info("Tadqiqot: %s", category)
        notes = self.research(category, avoid_titles)
        log.info("Ssenariy yozilmoqda")
        return self.write_script(category, notes)

    def draft_comment_reply(self, video_title: str, comment: str, author: str) -> CommentReply:
        prompt = (
            f"Sen ilmiy-ommabop YouTube kanali egasi nomidan kommentlarga javob yozasan. "
            f"Video: «{video_title}». Muallif: {author}.\nKomment:\n{comment}\n\n"
            "Kommentning tilida, samimiy, qisqa (1-3 gap) va aniq javob yoz. Agar savol bo'lsa, "
            "bilganingcha ilmiy asoslangan javob ber; tibbiy shaxsiy maslahat berma, shifokorga murojaat "
            "qilishni tavsiya et. Spam, reklama yoki haqorat bo'lsa should_reply=false."
        )
        resp = self.client.beta.messages.parse(
            model=self.model,
            max_tokens=4000,
            betas=[FALLBACK_BETA],
            fallbacks="default",
            thinking={"type": "adaptive"},
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": prompt}],
            output_format=CommentReply,
        )
        self._check(resp)
        return resp.parsed_output
