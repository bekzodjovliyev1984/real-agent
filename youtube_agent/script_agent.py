"""C. Ssenariy: faqat tasdiqlangan da'volardan hook -> setup -> development -> payoff hikoyasi."""

from __future__ import annotations

import logging

from .categories import render_prompt
from .llm import LLM
from .schemas import PUBLISHABLE_STATUSES, Claim, ScriptDraft, TopicDraft

log = logging.getLogger(__name__)
WORDS_PER_SECOND = 2.2  # o'zbekcha diktor nutqi uchun o'rtacha (so'zlar uzun)


def word_count(text: str) -> int:
    return len(text.split())


def claims_block(claims: list[Claim]) -> str:
    lines = []
    for c in claims:
        q = f" (izoh: {c.qualification})" if c.qualification else ""
        lines.append(f"- {c.id} [{c.status.value}]: {c.claim}{q}")
    return "\n".join(lines)


def validate_script(draft: ScriptDraft, allowed_ids: set[str], min_words: int, max_words: int) -> ScriptDraft:
    if not draft.beats:
        raise ValueError("beats bo'sh")
    if draft.beats[0].purpose != "hook":
        raise ValueError("birinchi beat purpose='hook' bo'lishi kerak")
    if draft.beats[-1].purpose != "payoff":
        raise ValueError("oxirgi beat purpose='payoff' bo'lishi kerak")
    for b in draft.beats:
        if not b.text.strip():
            raise ValueError("bo'sh beat matni")
        unknown = set(b.claim_ids) - allowed_ids
        if unknown:
            raise ValueError(f"tasdiqlanmagan yoki noma'lum da'volar ishlatilgan: {sorted(unknown)}. "
                             f"Faqat shulardan foydalan: {sorted(allowed_ids)}")
        if any(ch.isdigit() for ch in b.text):
            raise ValueError(f"diktor matnida raqam belgisi bor, so'z bilan yoz: {b.text!r}")
    words = sum(word_count(b.text) for b in draft.beats)
    if not (min_words <= words <= max_words):
        raise ValueError(f"ssenariy {words} so'z; {min_words}-{max_words} so'z oralig'ida bo'lishi kerak")
    if not draft.title.strip():
        raise ValueError("sarlavha bo'sh")
    if "#shorts" not in draft.title.lower():
        draft.title = f"{draft.title.strip()[:90]} #shorts"
    draft.title = draft.title[:100]
    return draft


def write_script(llm: LLM, category: str, topic: TopicDraft, claims: list[Claim],
                 min_seconds: float, max_seconds: float) -> ScriptDraft:
    usable = [c for c in claims if c.status in PUBLISHABLE_STATUSES]
    if len(usable) < 2:
        raise ValueError(f"tasdiqlangan da'volar juda kam ({len(usable)}): bu mavzuda video qilib bo'lmaydi")
    min_words, max_words = int(min_seconds * WORDS_PER_SECOND), int(max_seconds * WORDS_PER_SECOND)
    prompt = render_prompt("script", min_dur=int(min_seconds), max_dur=int(max_seconds), words_min=min_words,
                           words_max=max_words, category=category, topic=topic.topic, angle=topic.angle,
                           question=topic.central_question, claims=claims_block(usable))
    ids = {c.id for c in usable}
    script = llm.parse_validated(prompt, ScriptDraft, lambda d: validate_script(d, ids, min_words, max_words),
                                 effort="high")
    log.info("Ssenariy: %s (%d so'z)", script.title, sum(word_count(b.text) for b in script.beats))
    return script
