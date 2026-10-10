"""Mavzu topish, internetdan ma'lumot yig'ish, ssenariy va komment javoblari yozish.

Ikki provayder qo'llab-quvvatlanadi: Claude (Anthropic) va OpenAI. Tanlov: LLM_PROVIDER.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

FALLBACK_BETA = "server-side-fallback-2026-07-01"
WEB_SEARCH = {"type": "web_search_20260209", "name": "web_search", "max_uses": 8}


class Scene(BaseModel):
    narration: str = Field(description="Diktor matni: 1-2 qisqa, jonli gap (10-25 so'z)")
    visual_query: str = Field(description="Shu sahnaga mos stok-video qidiruvi, INGLIZCHA, 2-4 so'z (masalan: 'brain neurons glowing')")
    image_prompt: str = Field(description="Agar video topilmasa, AI rasm uchun inglizcha batafsil tavsif (matnsiz, fotorealistik)")


class VideoPlan(BaseModel):
    title: str = Field(description="Shorts sarlavhasi: 60 belgigacha, hayratlantiruvchi, oxirida #shorts")
    description: str = Field(description="2-3 gaplik tavsif, manbalar va 3-5 hashtag")
    tags: list[str] = Field(description="8-12 ta teg")
    hook_text: str = Field(description="Birinchi 2 soniyada ekran tepasida turadigan 2-5 so'zlik katta yozuv")
    scenes: list[Scene] = Field(description="5-8 ta sahna; birinchisi - hook, oxirgisi - qisqa yakun")
    sources: list[str] = Field(description="Foydalanilgan manbalar URL'lari")


class CommentReply(BaseModel):
    should_reply: bool = Field(description="Spam, haqorat yoki javob talab qilmaydigan bo'lsa false")
    reply: str = Field(description="Javob matni (should_reply false bo'lsa bo'sh)")
    reason: str = Field(description="Qisqa izoh: nega shunday qaror qilindi")


class ContentRefused(RuntimeError):
    pass


# ---------------------------------------------------------------- umumiy promptlar
def research_prompt(category: str, avoid_titles: list[str]) -> str:
    avoid = "\n".join(f"- {t}" for t in avoid_titles[-60:]) or "(hali yo'q)"
    return (
        f"Sen viral YouTube Shorts kanali uchun yangilik ovchisisan. Kategoriya: «{category}».\n"
        "Veb-qidiruv orqali OXIRGI 1-3 HAFTADAGI eng hayratlanarli, odamlar do'stiga aytib beradigan "
        "BITTA yangilik yoki kashfiyotni top (yangi texnologiya, rekord, g'aroyib kashfiyot, kutilmagan "
        "tadqiqot natijasi). Zerikarli, faqat mutaxassislarga qiziq mavzularni tanlama.\n"
        "Ishonchli manbalar: yirik nashrlar, ilmiy jurnallar, universitetlar, NASA, WHO va h.k.\n"
        f"Avval chiqqan videolar (takrorlama):\n{avoid}\n\n"
        "Natija: yangilik nima, nega hayratlanarli, oddiy odam hayotiga qanday ta'sir qiladi, "
        "3-5 ta aniq fakt (raqamlar bilan) va manba URL'lari."
    )


def script_prompt(language: str, category: str, research_notes: str) -> str:
    return (
        f"Quyidagi yangilik asosida {language} tilida 35-50 soniyalik YouTube Shorts ssenariysini yoz "
        f"(jami 90-130 so'z). Kategoriya: {category}.\n"
        "QOIDALAR:\n"
        "- 1-sahna HOOK: tomoshabinni 2 soniyada ushlab qoladigan hayratlantiruvchi gap "
        "(masalan: 'Olimlar hozirgina ... qildi!', 'Buni bilsangiz hayron qolasiz...'). Salomlashish YO'Q.\n"
        "- Yangilik kabi gapir: kim, nima qildi, nima uchun bu muhim. Jonli, so'zlashuv tili, qisqa gaplar.\n"
        "- Viktorina, test savoli, 'savol: ...' kabi sarlavhalar, ro'yxatlar va quruq raqamlar to'plami YO'Q.\n"
        "- Raqamlarni oddiy qilib ayt ('deyarli 2 baravar', '50 yorug'lik yili uzoqda').\n"
        "- Maxsus belgilar (⊕, ±, Å, ~) ishlatma - faqat oddiy harflar va raqamlar.\n"
        "- Oxirgi sahna: 1 gaplik kuchli xulosa + 'Bunday yangiliklar uchun obuna bo'ling!'.\n"
        "- Faqat tadqiqotdagi faktlardan foydalan, o'ylab topma.\n"
        "- Tibbiyot bo'lsa tavsifga 'Ma'lumot uchun, shifokor maslahatining o'rnini bosmaydi' qo'sh.\n"
        "- Har sahna uchun visual_query - aynan shu gapga mos, chiroyli kadr beradigan inglizcha qidiruv.\n\n"
        f"TADQIQOT:\n{research_notes}"
    )


def comment_prompt(video_title: str, comment: str, author: str) -> str:
    return (
        f"Sen ilmiy-ommabop YouTube kanali egasi nomidan kommentlarga javob yozasan. "
        f"Video: «{video_title}». Muallif: {author}.\nKomment:\n{comment}\n\n"
        "Kommentning tilida, samimiy, qisqa (1-3 gap) va aniq javob yoz. Agar savol bo'lsa, "
        "bilganingcha ilmiy asoslangan javob ber; tibbiy shaxsiy maslahat berma, shifokorga murojaat "
        "qilishni tavsiya et. Spam, reklama yoki haqorat bo'lsa should_reply=false."
    )


class BaseCreator:
    """Provayderlar uchun umumiy oqim: tadqiqot -> ssenariy."""

    def __init__(self, model: str, language: str):
        self.model = model
        self.language = language

    def research(self, category: str, avoid_titles: list[str]) -> str:
        raise NotImplementedError

    def write_script(self, category: str, research_notes: str) -> VideoPlan:
        raise NotImplementedError

    def draft_comment_reply(self, video_title: str, comment: str, author: str) -> CommentReply:
        raise NotImplementedError

    def create_video_plan(self, category: str, avoid_titles: list[str]) -> VideoPlan:
        log.info("Tadqiqot (%s): %s", type(self).__name__, category)
        notes = self.research(category, avoid_titles)
        log.info("Ssenariy yozilmoqda")
        plan = self.write_script(category, notes)
        if "#shorts" not in plan.title.lower():
            plan.title = f"{plan.title[:90]} #shorts"
        plan.title = plan.title[:100]
        plan.description = plan.description[:4900]
        return plan


# ---------------------------------------------------------------------- Claude
class ClaudeCreator(BaseCreator):
    FALLBACK_BETA = "server-side-fallback-2026-07-01"
    WEB_SEARCH = {"type": "web_search_20260209", "name": "web_search", "max_uses": 8}

    def __init__(self, model: str, language: str):
        import anthropic

        super().__init__(model, language)
        self.client = anthropic.Anthropic()

    def _check(self, resp) -> None:
        if resp.stop_reason == "refusal":
            raise ContentRefused(f"Claude so'rovni rad etdi: {resp.stop_details}")

    def research(self, category: str, avoid_titles: list[str]) -> str:
        messages: list = [{"role": "user", "content": research_prompt(category, avoid_titles)}]
        for _ in range(5):  # pause_turn bo'lsa davom ettiramiz
            resp = self.client.beta.messages.create(
                model=self.model,
                max_tokens=16000,
                betas=[self.FALLBACK_BETA],
                fallbacks="default",
                thinking={"type": "adaptive"},
                output_config={"effort": "high"},
                tools=[self.WEB_SEARCH],
                messages=messages,
            )
            self._check(resp)
            if resp.stop_reason == "pause_turn":
                messages = [*messages, {"role": "assistant", "content": resp.content}]
                continue
            return "\n".join(b.text for b in resp.content if b.type == "text")
        raise RuntimeError("Tadqiqot juda uzoq davom etdi (pause_turn chegarasi)")

    def _parse(self, prompt: str, schema, effort: str, max_tokens: int):
        resp = self.client.beta.messages.parse(
            model=self.model,
            max_tokens=max_tokens,
            betas=[self.FALLBACK_BETA],
            fallbacks="default",
            thinking={"type": "adaptive"},
            output_config={"effort": effort},
            messages=[{"role": "user", "content": prompt}],
            output_format=schema,
        )
        self._check(resp)
        return resp.parsed_output

    def write_script(self, category: str, research_notes: str) -> VideoPlan:
        return self._parse(script_prompt(self.language, category, research_notes), VideoPlan, "medium", 16000)

    def draft_comment_reply(self, video_title: str, comment: str, author: str) -> CommentReply:
        return self._parse(comment_prompt(video_title, comment, author), CommentReply, "low", 4000)


# ---------------------------------------------------------------------- OpenAI
class OpenAICreator(BaseCreator):
    def __init__(self, model: str, language: str):
        from openai import OpenAI

        super().__init__(model, language)
        self.client = OpenAI()

    def research(self, category: str, avoid_titles: list[str]) -> str:
        resp = self.client.responses.create(
            model=self.model,
            input=research_prompt(category, avoid_titles),
            tools=[{"type": "web_search"}],
            reasoning={"effort": "medium"},
        )
        if not resp.output_text:
            raise ContentRefused(f"OpenAI javob qaytarmadi: {resp.status}")
        return resp.output_text

    def _parse(self, prompt: str, schema, effort: str):
        resp = self.client.responses.parse(
            model=self.model,
            input=prompt,
            text_format=schema,
            reasoning={"effort": effort},
        )
        if resp.output_parsed is None:
            raise ContentRefused(f"OpenAI so'rovni rad etdi yoki javob bo'sh: {resp.status}")
        return resp.output_parsed

    def write_script(self, category: str, research_notes: str) -> VideoPlan:
        return self._parse(script_prompt(self.language, category, research_notes), VideoPlan, "medium")

    def draft_comment_reply(self, video_title: str, comment: str, author: str) -> CommentReply:
        return self._parse(comment_prompt(video_title, comment, author), CommentReply, "low")


def make_creator(provider: str, model: str, language: str) -> BaseCreator:
    provider = provider.lower()
    if provider == "claude":
        return ClaudeCreator(model, language)
    if provider == "openai":
        return OpenAICreator(model, language)
    raise ValueError(f"Noma'lum LLM_PROVIDER: {provider} (claude yoki openai bo'lishi kerak)")
