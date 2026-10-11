"""Mavzu topish, internetdan ma'lumot yig'ish, ssenariy va komment javoblari yozish.

Ikki provayder qo'llab-quvvatlanadi: Claude (Anthropic) va OpenAI. Tanlov: LLM_PROVIDER.
"""

from __future__ import annotations

import logging

from typing import Literal

from pydantic import BaseModel, Field

log = logging.getLogger(__name__)


class Scene(BaseModel):
    narration: str = Field(description="Diktor o'qiydigan matn: 1-2 qisqa, jonli gap (8-22 so'z), OVOZGA MOS yozilgan "
                                       "(raqamlar so'z bilan, chet el nomlari o'zbekcha talaffuzda, qisqartmalarsiz)")
    headline: str = Field(description="Ekran tepasidagi KATTA yozuv: raqam+birlik yoki kalit so'z, 1-3 so'z (masalan: '8 DAQIQA', '4,3 MLN QUYOSH', 'GPT-6', '1-BEKAT')")
    subline: str = Field(description="Katta yozuv tagidagi kichik izoh, 2-5 so'z (masalan: 'QUYOSH - YER · YORUG'LIK')")
    accent: Literal["orange", "cyan", "white", "yellow"] = Field(description="Katta yozuv rangi")
    image_source: Literal["source_article", "search"] = Field(
        description="source_article - manba maqolaning asosiy rasmi (yangilikning o'zi haqida sahnalar uchun); "
                    "search - image_query bo'yicha rasm qidirish")
    image_query: str = Field(description="Aniq obyekt nomi INGLIZCHA, rasm qidirish uchun (masalan: 'Sagittarius A* black hole', "
                                         "'Neptune Voyager 2', 'NVIDIA Blackwell GPU', 'mRNA vaccine vial')")
    image_prompt: str = Field(description="Rasm topilmasa AI chizishi uchun inglizcha tavsif (matnsiz, fotorealistik, qora fon)")


class VideoPlan(BaseModel):
    title: str = Field(description="Shorts sarlavhasi: 60 belgigacha, hayratlantiruvchi, oxirida #shorts")
    description: str = Field(description="2-3 gaplik tavsif, manbalar va 3-5 hashtag")
    tags: list[str] = Field(description="8-12 ta teg")
    scenes: list[Scene] = Field(description="8-12 ta sahna; birinchisi - hook, oxirgisi - qisqa yakun")
    sources: list[str] = Field(description="Yangilik olingan rasmiy sahifalar URL'lari (eng muhimi birinchi)")


class CommentReply(BaseModel):
    should_reply: bool = Field(description="Spam, haqorat yoki javob talab qilmaydigan bo'lsa false")
    reply: str = Field(description="Javob matni (should_reply false bo'lsa bo'sh)")
    reason: str = Field(description="Qisqa izoh: nega shunday qaror qilindi")


class ContentRefused(RuntimeError):
    pass


# Har bir soha uchun ma'lumot olinadigan rasmiy manbalar (faqat shu saytlardan qidiriladi)
CATEGORY_SOURCES: dict[str, list[str]] = {
    "Sun'iy intellekt": ["anthropic.com", "openai.com", "deepmind.google", "blog.google", "x.ai",
                         "mistral.ai", "nvidia.com", "nvidianews.nvidia.com", "ai.meta.com"],
    "Koinot": ["nasa.gov", "esa.int", "spacex.com", "blueorigin.com", "uzspace.uz", "gov.uz",
               "jpl.nasa.gov", "science.nasa.gov", "webbtelescope.org"],
    "Tibbiyot": ["who.int", "nih.gov", "cdc.gov", "fda.gov", "nejm.org", "thelancet.com", "nature.com",
                 "bmj.com", "mayoclinic.org", "ssv.uz"],
    "Ilm-fan": ["nature.com", "science.org", "home.cern", "mit.edu", "caltech.edu", "max-planck.de",
                "newscientist.com", "scientificamerican.com", "phys.org"],
}


def category_domains(category: str) -> list[str]:
    return CATEGORY_SOURCES.get(category, [])


# ---------------------------------------------------------------- umumiy promptlar
def research_prompt(category: str, avoid_titles: list[str]) -> str:
    avoid = "\n".join(f"- {t}" for t in avoid_titles[-60:]) or "(hali yo'q)"
    domains = category_domains(category)
    where = ("FAQAT shu rasmiy saytlardagi ma'lumotdan foydalan: " + ", ".join(domains) + ".\n") if domains else ""
    return (
        f"Sen viral YouTube Shorts kanali uchun yangilik ovchisisan. Soha: «{category}».\n"
        f"{where}"
        "Veb-qidiruv orqali OXIRGI 1-3 HAFTADAGI eng hayratlanarli BITTA yangilikni top: yangi model yoki "
        "mahsulot, kosmik missiya natijasi, rekord, g'aroyib kashfiyot, muhim tibbiy yutuq. Oddiy odam "
        "do'stiga aytib beradigan, raqamlari kuchli mavzu bo'lsin.\n"
        f"Avval chiqqan videolar (takrorlama):\n{avoid}\n\n"
        "Natija: yangilik nima, kim e'lon qildi, nega hayratlanarli, 5-8 ta aniq raqam/fakt va ularni "
        "tasavvur qilish uchun taqqoslashlar (masalan 'Quyoshdan 4 mln marta og'ir'), hamda rasmiy "
        "sahifalar URL'lari (eng asosiysi birinchi)."
    )


def script_prompt(language: str, category: str, research_notes: str) -> str:
    return (
        f"Quyidagi yangilik asosida {language} tilida 45-75 soniyalik YouTube Shorts ssenariysini yoz "
        f"(jami 110-180 so'z, 8-12 sahna). Soha: {category}.\n"
        "USLUB (namuna: 'Eng katta qora tuynuk qanchalik katta?' kabi kanallar):\n"
        "- 1-sahna HOOK: savol yoki hayratlanarli da'vo, headline - mavzu nomi (masalan 'ENG KATTA QORA TUYNUK'), "
        "subline - qisqa savol ('QANCHALIK KATTA?'). Salomlashish YO'Q.\n"
        "- Har sahnada BITTA kuchli raqam yoki fakt. headline - shu raqam birligi bilan ('8 DAQIQA', "
        "'4,3 MLN QUYOSH', '2,5 KUN'), subline - u nimani anglatadi ('QUYOSH - YER · YORUG'LIK').\n"
        "- Tushunarli taqqoslashlar orqali hikoya qil: kichikdan kattaga, bekatma-bekat, oddiy narsadan "
        "hayratlanarli natijaga. Jonli so'zlashuv tili, qisqa gaplar.\n"
        "- Viktorina, test savollari, quruq ro'yxatlar YO'Q. Maxsus belgilar (⊕, ±, Å, ~) YO'Q.\n"
        "- Oxirgi sahna: kuchli xulosa + 'Obuna bo'ling!'.\n"
        "- Faqat tadqiqotdagi faktlar, o'ylab topma.\n"
        "DIKTOR MATNI (narration) - uni o'zbek ovoz dasturi o'qiydi, shuning uchun:\n"
        "- Sof, tabiiy o'zbek adabiy tili; rus/ingliz tilidan so'zma-so'z tarjimaga o'xshagan iboralar YO'Q.\n"
        "- Raqamlarni SO'Z bilan yoz: 'to'rt million uch yuz ming', 'ming to'qqiz yuz yetmish yettinchi yilda', "
        "'sakkiz daqiqa'. Raqam belgisi (4,3 / 1977 / 25%) YO'Q - ular faqat headline'da.\n"
        "- Chet el nomlarini o'zbekcha o'qilishicha yoz: 'Jeyms Uebb teleskopi', 'Sagittarius' -> 'Sagittarius A yulduzi', "
        "'OpenAI' -> 'Open Ey Ay', 'NVIDIA' -> 'Nvidia', 'SpaceX' -> 'Speys Iks', 'GPT' -> 'Ji Pi Ti'.\n"
        "- Qisqartmalarni ochib yoz yoki o'qilishicha yoz: 'NASA' -> 'NASA' (so'z sifatida o'qiladi), "
        "'mRNK' -> 'informatsion RNK', 'km' -> 'kilometr'.\n"
        "- O'zbek lotin imlosi: o' va g' harflari, tutuq belgisi (ma'lumot). Qavslar, tire, belgilar YO'Q.\n"
        "- Qisqa gaplar (12 so'zdan kam), har gapda bitta fikr - ovoz tabiiyroq chiqadi.\n"
        "- RASMLAR faqat shu mavzuga oid bo'lsin: image_query - aynan sahnadagi obyekt (sayyora nomi, "
        "teleskop, kompaniya mahsuloti, kasallik/dori nomi), umumiy so'zlar ('technology', 'people') YO'Q. "
        "Yangilikning o'zi haqidagi sahnalarda image_source=source_article.\n"
        "- Tibbiyot bo'lsa tavsifga 'Ma'lumot uchun, shifokor maslahatining o'rnini bosmaydi' qo'sh.\n\n"
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

    def _web_search(self, category: str) -> dict:
        tool = dict(self.WEB_SEARCH)
        if category_domains(category):
            tool["allowed_domains"] = category_domains(category)
        return tool

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
                tools=[self._web_search(category)],
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

    @staticmethod
    def _web_search(category: str) -> dict:
        tool: dict = {"type": "web_search"}
        if category_domains(category):
            tool["filters"] = {"allowed_domains": category_domains(category)}
        return tool

    def research(self, category: str, avoid_titles: list[str]) -> str:
        resp = self.client.responses.create(
            model=self.model,
            input=research_prompt(category, avoid_titles),
            tools=[self._web_search(category)],
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
