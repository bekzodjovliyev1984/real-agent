"""Modullar orasidagi JSON shartnomalar (Pydantic).

Ikki xil model bor:
- *Draft modellar* - AI (Claude/OpenAI) structured output bilan qaytaradi. Ularda cheklov kalit so'zlari yo'q,
  chunki provayderlarning strict JSON schema rejimi ularni qo'llamaydi.
- *Ichki modellar* (ShortPlan, AssetMeta, QAReport...) - qat'iy tekshiruv (validator) bilan. AI javobi shu
  modellarga aylantiriladi; xato bo'lsa, xato matni bilan AI'dan qayta so'raladi.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

MIN_DURATION, MAX_DURATION = 15.0, 60.0
URL_RE = re.compile(r"^https?://[^\s/$.?#][^\s]*\.[^\s]+$", re.I)


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------- enums
class JobState(str, Enum):
    planned = "planned"
    researched = "researched"
    scripted = "scripted"
    assets_ready = "assets_ready"
    audio_ready = "audio_ready"
    rendered = "rendered"
    qa_failed = "qa_failed"
    approved = "approved"
    needs_review = "needs_review"
    published = "published"
    rejected = "rejected"  # egasi Telegram'da rad etdi


class VerificationStatus(str, Enum):
    verified = "verified"        # manba bilan to'liq tasdiqlangan
    qualified = "qualified"      # tasdiqlangan, lekin ehtiyotkor ifoda / izoh bilan
    unverified = "unverified"    # manba topilmadi - nashrni bloklaydi
    false = "false"              # manba rad etadi - ishlatilmaydi


PUBLISHABLE_STATUSES = {VerificationStatus.verified, VerificationStatus.qualified}

SourceType = Literal["stock_video", "archival_footage", "source_image", "still_image", "graphic", "ai_video"]
HookType = Literal["question", "contradiction", "surprising_number", "myth_bust", "what_if", "mystery", "news_reveal"]
Transition = Literal["cut", "crossfade"]
SoundEffect = Literal["none", "whoosh", "pop", "ding", "impact", "riser"]
MusicMood = Literal["none", "calm", "upbeat", "mysterious", "dramatic", "inspiring"]
BeatPurpose = Literal["hook", "setup", "development", "payoff"]


# ------------------------------------------------------------- AI draftlari
class SourceDraft(BaseModel):
    title: str = Field(description="Manba sahifasining sarlavhasi")
    url: str = Field(description="To'liq URL - faqat veb-qidiruvda haqiqatan ko'rilgan manzil")
    excerpt: str = Field(description="Da'voni tasdiqlovchi qisqa iqtibos (asl tilida)")


class ClaimDraft(BaseModel):
    id: str = Field(description="claim_01, claim_02 ...")
    claim: str = Field(description="Bitta aniq faktik da'vo (o'zbekcha)")
    status: Literal["verified", "qualified", "unverified", "false"]
    sources: list[SourceDraft]
    qualification: str = Field(description="Noaniqlik yoki kerakli izoh; bo'lmasa bo'sh qator")


class TopicDraft(BaseModel):
    topic: str = Field(description="Mavzu - bitta aniq yangilik yoki hodisa")
    angle: str = Field(description="Qaysi qiziq tomondan hikoya qilinadi")
    why_interesting: str
    central_question: str = Field(description="Tomoshabin javobini bilishni xohlaydigan savol")
    visual_potential: str = Field(description="Buni qanday kadrlar bilan ko'rsatish mumkin")
    claims: list[ClaimDraft]


class FactCheckDraft(BaseModel):
    claims: list[ClaimDraft]


class BeatDraft(BaseModel):
    purpose: BeatPurpose
    text: str = Field(description="Diktor matni (ovozga mos)")
    claim_ids: list[str]


class ScriptDraft(BaseModel):
    title: str
    hook_type: HookType
    hook: str
    beats: list[BeatDraft]
    description: str
    tags: list[str]
    music_mood: MusicMood


class SceneDraft(BaseModel):
    voiceover_text: str = Field(description="Shu sahnada aytiladigan matn (ovozga mos: raqamlar so'z bilan)")
    subtitle_text: str = Field(description="Ekranda ko'rinadigan subtitr matni (to'g'ri imlo, raqamlar raqam bilan bo'lishi mumkin)")
    estimated_duration: float = Field(description="Taxminiy davomiylik, soniya")
    visual_description: str = Field(description="Kadrda aniq nima ko'rinishi kerak")
    visual_purpose: str = Field(description="Bu kadr tomoshabinga nimani tushuntiradi")
    visual_source_type: SourceType
    visual_search_queries: list[str] = Field(description="2-4 ta INGLIZCHA qidiruv so'rovi, eng aniqdan umumiyroqqa")
    video_generation_prompt: str = Field(description="AI video uchun inglizcha prompt; kerak bo'lmasa bo'sh qator")
    on_screen_text: str = Field(description="Ekran tepasidagi katta yozuv (raqam yoki kalit so'z, 1-3 so'z); bo'lmasa bo'sh")
    on_screen_subtext: str = Field(description="Katta yozuv tagidagi kichik izoh; bo'lmasa bo'sh")
    sound_effect: SoundEffect
    transition: Transition
    related_claim_ids: list[str]
    relevance_criteria: str = Field(description="Kadr mos deb hisoblanishi uchun unda nima ko'rinishi SHART")


class StoryboardDraft(BaseModel):
    scenes: list[SceneDraft]


# ------------------------------------------------------------ ichki modellar
class SourceRef(BaseModel):
    title: str
    url: str
    excerpt: str = ""
    reachable: bool | None = None  # fact-checker HTTP orqali tekshirgan natija

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        if not URL_RE.match(v.strip()):
            raise ValueError(f"noto'g'ri URL: {v!r}")
        return v.strip()


class Claim(BaseModel):
    id: str
    claim: str
    status: VerificationStatus
    sources: list[SourceRef] = []
    qualification: str = ""

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not re.fullmatch(r"claim_\d{2,3}", v):
            raise ValueError(f"da'vo ID formati claim_01 bo'lishi kerak, keldi: {v!r}")
        return v

    @model_validator(mode="after")
    def _sources_for_verified(self) -> "Claim":
        if self.status in PUBLISHABLE_STATUSES and not self.sources:
            raise ValueError(f"{self.id}: tasdiqlangan da'voda kamida bitta manba bo'lishi shart")
        return self


class Scene(BaseModel):
    id: int = Field(ge=1)
    voiceover_text: str = Field(min_length=3)
    subtitle_text: str = Field(min_length=3)
    estimated_duration: float = Field(ge=1.0, le=20.0)
    visual_description: str = Field(min_length=5)
    visual_purpose: str = ""
    visual_source_type: SourceType
    visual_search_queries: list[str] = Field(min_length=1)
    video_generation_prompt: str | None = None
    on_screen_text: str = ""
    on_screen_subtext: str = ""
    sound_effect: SoundEffect = "none"
    transition: Transition = "cut"
    related_claim_ids: list[str] = []
    relevance_criteria: str = ""

    @field_validator("voiceover_text", "subtitle_text", "visual_description")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("bo'sh bo'lmasligi kerak")
        return v.strip()


class ShortPlan(BaseModel):
    title: str = Field(min_length=5, max_length=100)
    language: Literal["uz"] = "uz"
    category: str
    topic: str
    target_duration_seconds: float = Field(ge=MIN_DURATION, le=MAX_DURATION)
    hook_type: HookType
    hook: str
    description: str = ""
    tags: list[str] = []
    music_mood: MusicMood = "none"
    claims: list[Claim]
    scenes: list[Scene] = Field(min_length=3)

    @model_validator(mode="after")
    def _consistency(self) -> "ShortPlan":
        ids = [s.id for s in self.scenes]
        if ids != list(range(1, len(ids) + 1)):
            raise ValueError(f"sahna ID'lari 1 dan ketma-ket bo'lishi kerak, keldi: {ids}")
        claim_ids = {c.id for c in self.claims}
        for s in self.scenes:
            unknown = set(s.related_claim_ids) - claim_ids
            if unknown:
                raise ValueError(f"sahna {s.id}: noma'lum da'vo ID'lari {sorted(unknown)}")
        est = sum(s.estimated_duration for s in self.scenes)
        if not (MIN_DURATION * 0.8 <= est <= MAX_DURATION * 1.1):
            raise ValueError(f"sahnalar taxminiy jami davomiyligi {est:.0f}s - 15-60s oralig'ida bo'lishi kerak")
        return self

    def publication_blockers(self) -> list[str]:
        """Nashrni bloklaydigan faktik muammolar: sahnada ishlatilgan har bir da'vo tasdiqlangan bo'lishi shart."""
        by_id = {c.id: c for c in self.claims}
        blockers = []
        for s in self.scenes:
            for cid in s.related_claim_ids:
                c = by_id[cid]
                if c.status not in PUBLISHABLE_STATUSES:
                    blockers.append(f"sahna {s.id}: '{c.claim}' da'vosi tasdiqlanmagan ({c.status.value})")
        return blockers


class AssetMeta(BaseModel):
    scene_id: int
    provider: str
    asset_id: str
    media_type: Literal["video", "image", "graphic"]
    source_url: str = ""           # yuklab olingan fayl manzili
    page_url: str = ""             # provayderdagi sahifa
    creator: str = ""
    license: str = ""
    license_url: str = ""
    license_verified: bool = False
    ai_generated: bool = False
    query: str = ""
    local_path: str = ""
    width: int = 0
    height: int = 0
    duration: float = 0.0
    relevance_score: float | None = None
    relevance_reason: str = ""
    fingerprint: str = ""
    cost_usd: float = 0.0
    downloaded_at: str = Field(default_factory=utcnow)

    def credit(self) -> str:
        who = f" / {self.creator}" if self.creator else ""
        lic = f" ({self.license})" if self.license else ""
        return f"{self.provider}{who}{lic}"


class WordTiming(BaseModel):
    text: str
    start: float
    end: float


class NarrationResult(BaseModel):
    provider: str
    voice: str
    model: str = ""
    raw_audio: str
    processed_audio: str = ""
    duration: float = 0.0
    speech_text: str
    words: list[WordTiming] = []          # speech_text so'zlari vaqti
    timing_source: Literal["tts", "alignment", "estimated"] = "estimated"
    asr_text: str = ""
    asr_similarity: float | None = None
    scene_bounds: list[float] = []        # har sahna boshlanish vaqti + oxiri
    loudness_lufs: float | None = None
    true_peak_db: float | None = None
    cost_usd: float = 0.0


class QAScores(BaseModel):
    storytelling: float = 0
    visual_relevance: float = 0
    audio_quality: float = 0
    subtitle_quality: float = 0
    technical_quality: float = 0


class QAReport(BaseModel):
    approved: bool = False
    attempt: int = 1
    technical_errors: list[str] = []
    factual_errors: list[str] = []
    audio_issues: list[str] = []
    visual_mismatch_issues: list[str] = []
    subtitle_issues: list[str] = []
    license_warnings: list[str] = []
    scores: QAScores = QAScores()
    scene_ids_to_fix: list[int] = []
    recommended_fixes: list[str] = []
    route_to: Literal["none", "visuals", "audio", "subtitles", "script", "human"] = "none"
    metrics: dict = {}
    notes: list[str] = []
    created_at: str = Field(default_factory=utcnow)


class SemanticReviewDraft(BaseModel):
    """AI tekshiruvchisi qaytaradigan javob (render qilingan kadrlarga qarab)."""
    storytelling: float
    visual_relevance: float
    subtitle_quality: float
    factual_errors: list[str]
    visual_mismatch_issues: list[str]
    subtitle_issues: list[str]
    scene_ids_to_fix: list[int]
    recommended_fixes: list[str]
    summary: str


class VisualCheckDraft(BaseModel):
    matches: bool
    score: float = Field(description="0-10: kadr sahna talabiga qanchalik mos")
    reason: str
