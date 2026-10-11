"""Claude (Anthropic) va OpenAI uchun yagona interfeys.

- research(): veb-qidiruv bilan erkin matn (faqat ko'rsatilgan saytlarda qidirish mumkin)
- parse(): Pydantic sxemasi bo'yicha tuzilgan javob; rasmlar (kadrlar) ham berilishi mumkin
- parse_validated(): javobni ichki qat'iy modelga aylantiradi; xato bo'lsa xato matni bilan qayta so'raydi

Har chaqiruvning token sarfi `usage` ro'yxatiga yoziladi (narxni hisoblash uchun).
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Callable, TypeVar

from pydantic import BaseModel, ValidationError

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)
R = TypeVar("R")


class LLMRefused(RuntimeError):
    pass


def _b64(path: Path) -> str:
    return base64.b64encode(Path(path).read_bytes()).decode()


class LLM:
    provider = "base"

    def __init__(self, model: str, cheap_model: str):
        self.model = model
        self.cheap_model = cheap_model
        self.usage: list[dict] = []

    def research(self, prompt: str, domains: list[str] | None = None, effort: str = "high") -> str:
        raise NotImplementedError

    def parse(self, prompt: str, schema: type[T], effort: str = "medium",
              images: list[Path] | None = None, cheap: bool = False) -> T:
        raise NotImplementedError

    def parse_validated(self, prompt: str, schema: type[T], convert: Callable[[T], R],
                        effort: str = "medium", attempts: int = 3) -> R:
        """AI javobini `convert` orqali qat'iy modelga aylantiradi; xato bo'lsa AI'ga xatoni ko'rsatib qayta so'raydi."""
        feedback = ""
        for i in range(1, attempts + 1):
            draft = self.parse(prompt + feedback, schema, effort=effort)
            try:
                return convert(draft)
            except (ValidationError, ValueError) as e:
                log.warning("AI javobi tekshiruvdan o'tmadi (%d/%d): %s", i, attempts, str(e)[:500])
                if i == attempts:
                    raise
                feedback = (f"\n\nOLDINGI JAVOBINGDA XATO BOR, TUZATIB QAYTA YOZ:\n{str(e)[:1500]}\n"
                            f"Oldingi javob:\n{draft.model_dump_json()[:6000]}")
        raise RuntimeError("unreachable")

    def _record(self, model: str, input_tokens: int, output_tokens: int, web_searches: int = 0, kind: str = "") -> None:
        self.usage.append({"provider": self.provider, "model": model, "kind": kind, "input_tokens": input_tokens,
                           "output_tokens": output_tokens, "web_searches": web_searches})


# --------------------------------------------------------------------- Claude
class ClaudeLLM(LLM):
    provider = "claude"
    FALLBACK_BETA = "server-side-fallback-2026-07-01"
    FALLBACK_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}

    def __init__(self, model: str, cheap_model: str):
        import anthropic

        super().__init__(model, cheap_model)
        self.client = anthropic.Anthropic()

    def _extra(self, model: str) -> dict:
        # Xavfsizlik klassifikatori rad etsa, server o'zi boshqa modelda qayta urinadi
        if model in self.FALLBACK_MODELS:
            return {"betas": [self.FALLBACK_BETA], "fallbacks": "default"}
        return {}

    def _check(self, resp) -> None:
        if resp.stop_reason == "refusal":
            raise LLMRefused(f"Claude so'rovni rad etdi: {resp.stop_details}")

    def _usage(self, resp, model: str, kind: str) -> None:
        u = resp.usage
        searches = getattr(getattr(u, "server_tool_use", None), "web_search_requests", 0) or 0
        self._record(model, u.input_tokens, u.output_tokens, searches, kind)

    def research(self, prompt: str, domains: list[str] | None = None, effort: str = "high") -> str:
        tool: dict = {"type": "web_search_20260209", "name": "web_search", "max_uses": 10}
        if domains:
            tool["allowed_domains"] = domains
        messages: list = [{"role": "user", "content": prompt}]
        for _ in range(5):  # pause_turn bo'lsa davom ettiramiz
            resp = self.client.beta.messages.create(
                model=self.model, max_tokens=16000, thinking={"type": "adaptive"},
                output_config={"effort": effort}, tools=[tool], messages=messages, **self._extra(self.model),
            )
            self._check(resp)
            self._usage(resp, self.model, "research")
            if resp.stop_reason == "pause_turn":
                messages = [*messages, {"role": "assistant", "content": resp.content}]
                continue
            return "\n".join(b.text for b in resp.content if b.type == "text")
        raise RuntimeError("Tadqiqot juda uzoq davom etdi (pause_turn chegarasi)")

    def parse(self, prompt: str, schema: type[T], effort: str = "medium",
              images: list[Path] | None = None, cheap: bool = False) -> T:
        model = self.cheap_model if cheap else self.model
        content: list | str = prompt
        if images:
            content = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": _b64(p)}}
                       for p in images] + [{"type": "text", "text": prompt}]
        resp = self.client.beta.messages.parse(
            model=model, max_tokens=16000, thinking={"type": "adaptive"}, output_config={"effort": effort},
            messages=[{"role": "user", "content": content}], output_format=schema, **self._extra(model),
        )
        self._check(resp)
        self._usage(resp, model, "parse")
        if resp.parsed_output is None:
            raise LLMRefused(f"Claude tuzilgan javob qaytarmadi (stop_reason={resp.stop_reason})")
        return resp.parsed_output


# --------------------------------------------------------------------- OpenAI
class OpenAILLM(LLM):
    provider = "openai"

    def __init__(self, model: str, cheap_model: str):
        from openai import OpenAI

        super().__init__(model, cheap_model)
        self.client = OpenAI()

    def _usage(self, resp, model: str, kind: str) -> None:
        u = resp.usage
        searches = sum(1 for item in (resp.output or []) if getattr(item, "type", "") == "web_search_call")
        self._record(model, getattr(u, "input_tokens", 0), getattr(u, "output_tokens", 0), searches, kind)

    def research(self, prompt: str, domains: list[str] | None = None, effort: str = "high") -> str:
        tool: dict = {"type": "web_search"}
        if domains:
            tool["filters"] = {"allowed_domains": domains}
        resp = self.client.responses.create(model=self.model, input=prompt, tools=[tool], reasoning={"effort": effort})
        self._usage(resp, self.model, "research")
        if not resp.output_text:
            raise LLMRefused(f"OpenAI javob qaytarmadi: {resp.status}")
        return resp.output_text

    def parse(self, prompt: str, schema: type[T], effort: str = "medium",
              images: list[Path] | None = None, cheap: bool = False) -> T:
        model = self.cheap_model if cheap else self.model
        content: list = [{"type": "input_text", "text": prompt}]
        for p in images or []:
            content.append({"type": "input_image", "image_url": f"data:image/jpeg;base64,{_b64(p)}"})
        resp = self.client.responses.parse(
            model=model, input=[{"role": "user", "content": content}], text_format=schema, reasoning={"effort": effort},
        )
        self._usage(resp, model, "parse")
        if resp.output_parsed is None:
            raise LLMRefused(f"OpenAI so'rovni rad etdi yoki javob bo'sh: {resp.status}")
        return resp.output_parsed


def make_llm(provider: str, model: str, cheap_model: str) -> LLM:
    provider = provider.lower()
    if provider == "claude":
        return ClaudeLLM(model, cheap_model)
    if provider == "openai":
        return OpenAILLM(model, cheap_model)
    raise ValueError(f"Noma'lum LLM_PROVIDER: {provider} (claude yoki openai bo'lishi kerak)")
