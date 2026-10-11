"""Taxminiy API narxlari (USD). Narxlar o'zgarib turadi - .env'dagi PRICE_* bilan yangilang.

Manbalar (2026-oktabr holatiga, uchinchi tomon jadvallari bir-biriga zid; rasmiy narx sahifasini tekshiring):
- OpenAI GPT-5: $1.25 / $10 (1M kirish/chiqish token), GPT-5 mini: $0.25 / $2
- Claude Opus 5.5: $4 / $20, Claude Haiku 5.5: $0.10 / $0.50
- Veb-qidiruv: ~$0.01 bitta qidiruv
- gpt-4o-mini-tts: ~$0.015 / daqiqa ovoz; whisper-1: $0.006 / daqiqa; Sora 2: ~$0.10 / soniya
"""

from __future__ import annotations

import os

MODEL_PRICES: dict[str, tuple[float, float]] = {
    "gpt-5": (1.25, 10.0),
    "gpt-5-mini": (0.25, 2.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.10, 0.50),
}
WEB_SEARCH_PRICE = float(os.environ.get("PRICE_WEB_SEARCH", "0.01"))
WHISPER_PER_MINUTE = float(os.environ.get("PRICE_WHISPER_PER_MIN", "0.006"))


def model_price(model: str) -> tuple[float, float]:
    env = os.environ.get(f"PRICE_{model.upper().replace('-', '_').replace('.', '_')}")
    if env:  # masalan PRICE_GPT_5=1.25,10
        a, b = env.split(",")
        return float(a), float(b)
    return MODEL_PRICES.get(model, (0.0, 0.0))


def llm_cost(usage: list[dict]) -> float:
    total = 0.0
    for u in usage:
        pin, pout = model_price(u["model"])
        total += u["input_tokens"] / 1e6 * pin + u["output_tokens"] / 1e6 * pout + u.get("web_searches", 0) * WEB_SEARCH_PRICE
    return round(total, 4)
