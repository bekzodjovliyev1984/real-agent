"""A. Mavzu tadqiqoti: veb-qidiruv bilan bitta qiziq, tushuntirsa bo'ladigan mavzu va da'volar topiladi."""

from __future__ import annotations

import logging
import re

from .categories import get_category, render_prompt
from .llm import LLM
from .schemas import TopicDraft

log = logging.getLogger(__name__)


def _normalize(draft: TopicDraft) -> TopicDraft:
    if not draft.claims:
        raise ValueError("kamida 3 ta faktik da'vo kerak, birorta ham yo'q")
    if len(draft.claims) < 3:
        raise ValueError(f"kamida 3 ta faktik da'vo kerak, keldi: {len(draft.claims)}")
    for i, c in enumerate(draft.claims, 1):
        c.id = f"claim_{i:02d}"
        c.status = "unverified"  # tasdiqlash keyingi bosqichda, alohida
    return draft


def research_topic(llm: LLM, category: str, avoid_titles: list[str],
                   performance_summary: str = "") -> tuple[TopicDraft, str]:
    cat = get_category(category)
    avoid = "\n".join(f"- {t}" for t in avoid_titles[-60:]) or "(hali yo'q)"
    domains_line = ("Ma'lumotni asosan shu rasmiy va nufuzli saytlardan ol: " + ", ".join(cat.domains)) if cat.domains else ""
    perf = f"Kanal statistikasi (faqat yo'nalish uchun, sabab-oqibat emas):\n{performance_summary}" if performance_summary else ""
    prompt = render_prompt("topic", category=cat.name, category_hint=cat.hint, domains_line=domains_line,
                           avoid=avoid, performance=perf)
    log.info("Mavzu qidirilmoqda: %s", cat.name)
    text = llm.research(prompt, domains=cat.domains or None)
    draft = llm.parse_validated(render_prompt("topic_parse", research=text), TopicDraft, _normalize)
    # AI matnda yo'q URL qo'shib yubormasin
    for c in draft.claims:
        c.sources = [s for s in c.sources if s.url and _url_in(s.url, text)]
    log.info("Mavzu: %s (%d ta da'vo)", draft.topic, len(draft.claims))
    return draft, text


def _url_in(url: str, text: str) -> bool:
    core = re.sub(r"^https?://(www\.)?", "", url).rstrip("/")
    return core[:60] in text
