"""B. Fakt-tekshiruv: har bir da'vo mustaqil veb-qidiruv bilan tekshiriladi.

Himoya qatlamlari (AI'ning ishonchli ohangi dalil emas):
1. Manba URL tekshiruv matnida haqiqatan uchrashi kerak (o'ylab topilgan URL tashlanadi).
2. URL HTTP orqali ochib ko'riladi: 404/410 yoki domen yo'q bo'lsa manba o'chiriladi.
3. Manbasi qolmagan da'vo avtomatik "unverified" bo'ladi va nashrni bloklaydi.
"""

from __future__ import annotations

import json
import logging
import re

import httpx

from .categories import render_prompt
from .llm import LLM
from .net import http_client
from .schemas import Claim, ClaimDraft, FactCheckDraft, SourceRef, VerificationStatus

log = logging.getLogger(__name__)
UA = {"User-Agent": "Mozilla/5.0 (compatible; UzScienceShortsFactCheck/1.0)"}


def _url_core(url: str) -> str:
    return re.sub(r"^https?://(www\.)?", "", url.strip()).rstrip("/")


def check_url(url: str, client: httpx.Client | None = None) -> bool | None:
    """True - sahifa ochildi; False - yo'q (404/410/domen yo'q); None - aniqlab bo'lmadi (403, 429, 5xx...)."""
    own = client is None
    client = client or http_client(12, UA)
    try:
        r = client.get(url)
        if r.status_code < 400:
            return True
        if r.status_code in (404, 410):
            return False
        return None
    except httpx.ConnectError:
        return False
    except httpx.HTTPError:
        return None
    finally:
        if own:
            client.close()


def to_claims(draft: FactCheckDraft, original_ids: list[str], evidence_text: str,
              url_checker=check_url) -> list[Claim]:
    by_id = {c.id: c for c in draft.claims}
    missing = [i for i in original_ids if i not in by_id]
    extra = [i for i in by_id if i not in original_ids]
    if extra:
        raise ValueError(f"noma'lum da'vo ID'lari: {extra}. Faqat shu ID'lardan foydalan: {original_ids}")
    claims: list[Claim] = []
    for cid in original_ids:
        d = by_id.get(cid)
        if d is None:
            claims.append(Claim(id=cid, claim="", status=VerificationStatus.unverified,
                                qualification="fakt-tekshiruvchi bu da'voni qaytarmadi"))
            continue
        sources: list[SourceRef] = []
        for s in d.sources:
            if not s.url or _url_core(s.url)[:60] not in evidence_text:
                log.warning("%s: manba URL tekshiruv matnida yo'q, tashlandi: %s", cid, s.url)
                continue
            try:
                ref = SourceRef(title=s.title, url=s.url, excerpt=s.excerpt)
            except ValueError:
                continue
            ref.reachable = url_checker(ref.url)
            if ref.reachable is False:
                log.warning("%s: manba ochilmadi (404/domen yo'q), tashlandi: %s", cid, s.url)
                continue
            sources.append(ref)
        status = VerificationStatus(d.status)
        qualification = d.qualification
        if status in (VerificationStatus.verified, VerificationStatus.qualified) and not sources:
            status = VerificationStatus.unverified
            qualification = (qualification + "; " if qualification else "") + "tasdiqlovchi manba URL'i tekshiruvdan o'tmadi"
        claims.append(Claim(id=cid, claim=d.claim, status=status, sources=sources, qualification=qualification))
    if missing:
        log.warning("Fakt-tekshiruvchi qaytarmagan da'volar: %s", missing)
    return claims


def verify_claims(llm: LLM, claims: list[ClaimDraft]) -> tuple[list[Claim], str]:
    payload = json.dumps([{"id": c.id, "claim": c.claim, "sources": [s.url for s in c.sources]} for c in claims],
                         ensure_ascii=False, indent=1)
    log.info("Fakt-tekshiruv: %d ta da'vo", len(claims))
    evidence = llm.research(render_prompt("fact_check", claims=payload), domains=None, effort="medium")
    ids = [c.id for c in claims]
    with http_client(12, UA) as http:
        result = llm.parse_validated(
            render_prompt("fact_check_parse", ids=", ".join(ids), verification=evidence), FactCheckDraft,
            lambda d: to_claims(d, ids, evidence, lambda u: check_url(u, http)),
        )
    counts: dict[str, int] = {}
    for c in result:
        counts[c.status.value] = counts.get(c.status.value, 0) + 1
    log.info("Fakt-tekshiruv natijasi: %s", counts)
    return result, evidence
