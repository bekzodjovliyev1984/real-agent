"""Umumiy HTTP mijoz.

Windows'da ba'zi tarmoqlarda IPv6 ulanish ishlamaydi va har so'rov IPv4'ga o'tishdan oldin ~20-40 soniya kutib
qoladi. Shuning uchun standart holatda IPv4 majburiy (FORCE_IPV4=0 bilan o'chirish mumkin).
"""

from __future__ import annotations

import os

import httpx

UA = {"User-Agent": "Mozilla/5.0 (compatible; UzScienceShorts/1.0; educational YouTube channel)"}


def http_client(timeout: float | httpx.Timeout = 30, headers: dict | None = None) -> httpx.Client:
    force_v4 = os.environ.get("FORCE_IPV4", "1").strip().lower() not in ("0", "false", "no")
    transport = httpx.HTTPTransport(local_address="0.0.0.0" if force_v4 else None, retries=2)
    return httpx.Client(transport=transport, timeout=timeout, follow_redirects=True, headers=headers or UA)
