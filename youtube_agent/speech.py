"""Diktor matnini ovoz dasturi uchun tayyorlash (o'zbek tili).

AI ssenariyni allaqachon "ovozga mos" yozadi; bu yerda esa qolib ketgan xatolar tuzatiladi:
apostroflar (oʻ, gʻ, tutuq belgisi), raqamlar so'z bilan, ortiqcha belgilar.
"""

from __future__ import annotations

import re

ONES = ["nol", "bir", "ikki", "uch", "toʻrt", "besh", "olti", "yetti", "sakkiz", "toʻqqiz"]
TENS = ["", "oʻn", "yigirma", "oʻttiz", "qirq", "ellik", "oltmish", "yetmish", "sakson", "toʻqson"]
SCALES = [(10**12, "trillion"), (10**9, "milliard"), (10**6, "million"), (1000, "ming")]
APOSTROPHES = "'`´‘’ʼʻ"
UNITS = {"%": "foiz", "°C": "daraja", "km": "kilometr", "kg": "kilogramm", "mln": "million", "mlrd": "milliard"}


def _under_thousand(n: int) -> str:
    parts = []
    if n >= 100:
        h = n // 100
        parts.append("yuz" if h == 1 else f"{ONES[h]} yuz")
        n %= 100
    if n >= 10:
        parts.append(TENS[n // 10])
        n %= 10
    if n:
        parts.append(ONES[n])
    return " ".join(parts)


def number_to_words(n: int) -> str:
    """Butun sonni o'zbekcha so'z bilan: 4300000 -> 'toʻrt million uch yuz ming'."""
    if n == 0:
        return ONES[0]
    if n < 0:
        return "minus " + number_to_words(-n)
    parts = []
    for value, name in SCALES:
        if n >= value:
            count = n // value
            # son "ming" bilan boshlansa "bir" aytilmaydi: 1977 -> "ming toʻqqiz yuz..."
            leading_ming = count == 1 and name == "ming" and not parts
            parts.append(name if leading_ming else f"{_under_thousand(count)} {name}")
            n %= value
    if n:
        parts.append(_under_thousand(n))
    return " ".join(parts)


def ordinal(n: int) -> str:
    """1 -> 'birinchi', 1977 -> 'ming toʻqqiz yuz yetmish yettinchi'."""
    words = number_to_words(n)
    return words + ("nchi" if words[-1] in "aeiou" else "inchi")


def _decimal_to_words(whole: str, frac: str) -> str:
    """4,3 -> 'toʻrt butun oʻndan uch'."""
    denom = {1: "oʻndan", 2: "yuzdan", 3: "mingdan"}.get(len(frac))
    if not denom:
        return f"{number_to_words(int(whole))} butun {number_to_words(int(frac))}"
    return f"{number_to_words(int(whole))} butun {denom} {number_to_words(int(frac))}"


def fix_apostrophes(text: str) -> str:
    """o' g' -> oʻ gʻ (rasmiy imlo); boshqa harflardan keyingi apostrof -> tutuq belgisi ʼ."""
    text = re.sub(rf"([oOgG])[{APOSTROPHES}]", lambda m: m.group(1) + "ʻ", text)
    return re.sub(rf"(?<=[A-Za-z])(?<![oOgG])[{APOSTROPHES}](?=[A-Za-z])", "ʼ", text)


def numbers_to_words(text: str) -> str:
    # 4,3 mln / 2.5 / 1 000 000 / 48
    text = re.sub(r"(?<=\d)[  ](?=\d{3}\b)", "", text)
    text = re.sub(r"(\d+)[.,](\d+)", lambda m: _decimal_to_words(m.group(1), m.group(2)), text)
    text = re.sub(r"(\d+)-(?=[^\W\d])", lambda m: ordinal(int(m.group(1))) + " ", text)  # 1977-yil, 2-bekat
    return re.sub(r"\d+", lambda m: number_to_words(int(m.group())), text)


def prepare_speech(text: str) -> str:
    """Ovoz dasturiga beriladigan yakuniy matn."""
    text = fix_apostrophes(text)
    for unit, word in UNITS.items():
        text = re.sub(rf"(?<=\d)\s*{re.escape(unit)}(?=\W|$)", f" {word}", text)
    text = numbers_to_words(text)
    text = re.sub(r"\b(foiz|daraja|million|milliard) (ga|da|dan)\b", r"\1\2", text)
    text = re.sub(r"[~±⊕*#_|<>\[\]{}]", " ", text)
    text = text.replace("—", ", ").replace("–", ", ").replace("…", ".")
    text = re.sub(r"\s+([,.!?])", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()
