"""Kanal sohalari va har biri uchun ishonchli manbalar ro'yxati."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from string import Template

PROMPTS_DIR = Path(__file__).parent / "prompts"


@dataclass(frozen=True)
class Category:
    name: str
    hint: str
    domains: list[str] = field(default_factory=list)


CATEGORIES: dict[str, Category] = {c.name: c for c in [
    Category("Sun'iy intellekt", "yangi AI modellar, agentlar, AI yordamida qilingan kashfiyotlar",
             ["anthropic.com", "openai.com", "deepmind.google", "blog.google", "x.ai", "mistral.ai",
              "nvidia.com", "nvidianews.nvidia.com", "ai.meta.com", "arxiv.org", "nature.com"]),
    Category("Yangi texnologiyalar", "yangi qurilmalar, gadjetlar, robotlar, energetika va aloqa texnologiyalari",
             ["apple.com", "news.samsung.com", "blog.google", "news.microsoft.com", "nvidianews.nvidia.com",
              "theverge.com", "techcrunch.com", "arstechnica.com", "wired.com", "ieee.org", "spectrum.ieee.org"]),
    Category("Yangi mashinalar", "yangi avtomobillar, elektromobillar, avtopilot, batareya texnologiyalari",
             ["tesla.com", "byd.com", "global.toyota", "group.mercedes-benz.com", "press.bmwgroup.com",
              "hyundainews.com", "uzautomotors.com", "motor1.com", "caranddriver.com", "electrek.co"]),
    Category("Ilm-fan", "yangi ilmiy kashfiyotlar va tajribalar, kundalik hodisalarning ilmiy izohi",
             ["nature.com", "science.org", "home.cern", "mit.edu", "caltech.edu", "mpg.de",
              "newscientist.com", "scientificamerican.com", "phys.org", "nih.gov", "eurekalert.org"]),
    Category("Ta'lim", "maktab va ta'limdagi yangiliklar, yangi o'qitish usullari, ta'limga oid tadqiqotlar",
             ["uzedu.uz", "edu.uz", "gov.uz", "uza.uz", "kun.uz", "daryo.uz", "gazeta.uz", "unesco.org",
              "oecd.org"]),
]}


def get_category(name: str) -> Category:
    return CATEGORIES.get(name) or Category(name, name)


def render_prompt(name: str, **values: object) -> str:
    """prompts/<name>.md shablonini $o'zgaruvchilar bilan to'ldiradi."""
    text = (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")
    return Template(text).substitute({k: str(v) for k, v in values.items()})
