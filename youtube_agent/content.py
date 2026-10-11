"""Kommentlarga javob loyihasi (javob faqat egasi Telegram'da ruxsat bergandan keyin yoziladi)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from .categories import render_prompt
from .llm import LLM


class CommentReply(BaseModel):
    should_reply: bool = Field(description="Spam, haqorat yoki javob talab qilmaydigan bo'lsa false")
    reply: str = Field(description="Javob matni (should_reply false bo'lsa bo'sh)")
    reason: str = Field(description="Qisqa izoh: nega shunday qaror qilindi")


def draft_comment_reply(llm: LLM, video_title: str, comment: str, author: str) -> CommentReply:
    prompt = render_prompt("comment", title=video_title, author=author, comment=comment)
    return llm.parse(prompt, CommentReply, effort="low", cheap=True)
