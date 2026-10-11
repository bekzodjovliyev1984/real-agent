"""Sahna rasmlarini faqat mavzuga oid manbalardan topish.

Tartib: manba maqolaning asosiy rasmi (og:image) -> NASA rasm arxivi (koinot) -> Wikimedia Commons
-> (ixtiyoriy) AI rasm -> (ixtiyoriy) Pixabay. Hech narsa topilmasa - oldingi sahna rasmi yoki qora fon.
"""

from __future__ import annotations

import base64
import io
import logging
import re
from dataclasses import dataclass, field
from html import unescape
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from PIL import Image

log = logging.getLogger(__name__)

UA = {"User-Agent": "YouTubeShortsAgent/1.0 (educational science channel)"}
MIN_SIDE = 480


@dataclass
class FoundImage:
    path: Path
    credit: str


@dataclass
class ImageFinder:
    category: str
    sources: list[str]
    pixabay_key: str = ""
    ai_images: bool = False
    stock_fallback: bool = False
    used: set[str] = field(default_factory=set)
    credits: list[str] = field(default_factory=list)
    _source_images: list[tuple[str, str]] | None = None
    _source_idx: int = 0

    def __post_init__(self):
        self.http = httpx.Client(timeout=30, follow_redirects=True, headers=UA)

    # ------------------------------------------------------------ yordamchilar
    def _save(self, url: str, out: Path) -> Path | None:
        if url in self.used:
            return None
        r = self.http.get(url)
        r.raise_for_status()
        img = Image.open(io.BytesIO(r.content))
        if min(img.size) < MIN_SIDE:
            return None
        img.convert("RGB").save(out.with_suffix(".jpg"), quality=92)
        self.used.add(url)
        return out.with_suffix(".jpg")

    # ------------------------------------------------------------- manbalar
    def _og_image(self, page_url: str) -> str | None:
        html = self.http.get(page_url).text[:400_000]
        for prop in ("og:image", "twitter:image", "og:image:url"):
            m = (re.search(rf'<meta[^>]+(?:property|name)=["\']{prop}["\'][^>]+content=["\']([^"\']+)', html, re.I)
                 or re.search(rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']{prop}["\']', html, re.I))
            if m:
                return urljoin(page_url, unescape(m.group(1)))
        return None

    def source_article(self, out: Path) -> FoundImage | None:
        if self._source_images is None:
            self._source_images = []
            for url in self.sources[:5]:
                try:
                    img = self._og_image(url)
                    if img:
                        self._source_images.append((img, urlparse(url).netloc.removeprefix("www.")))
                except Exception as e:
                    log.debug("og:image olinmadi %s: %s", url, e)
        while self._source_idx < len(self._source_images):
            img, site = self._source_images[self._source_idx]
            self._source_idx += 1
            path = self._save(img, out)
            if path:
                return FoundImage(path, site)
        return None

    def nasa(self, query: str, out: Path) -> FoundImage | None:
        r = self.http.get("https://images-api.nasa.gov/search", params={"q": query, "media_type": "image"})
        r.raise_for_status()
        for item in r.json().get("collection", {}).get("items", [])[:8]:
            links = item.get("links") or []
            if not links:
                continue
            href = links[0]["href"].replace("~thumb.jpg", "~large.jpg")
            try:
                path = self._save(href, out)
            except Exception:
                path = self._save(links[0]["href"], out)
            if path:
                return FoundImage(path, "NASA")
        return None

    def wikimedia(self, query: str, out: Path) -> FoundImage | None:
        r = self.http.get("https://commons.wikimedia.org/w/api.php", params={
            "action": "query", "format": "json", "generator": "search", "gsrnamespace": 6,
            "gsrsearch": f"{query} filetype:bitmap", "gsrlimit": 8, "prop": "imageinfo",
            "iiprop": "url|mime|extmetadata", "iiurlwidth": 1600,
        })
        r.raise_for_status()
        pages = sorted(r.json().get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 99))
        for page in pages:
            info = (page.get("imageinfo") or [{}])[0]
            if info.get("mime") not in ("image/jpeg", "image/png"):
                continue
            path = self._save(info.get("thumburl") or info["url"], out)
            if path:
                artist = re.sub("<[^>]+>", "", info.get("extmetadata", {}).get("Artist", {}).get("value", "")).strip()
                return FoundImage(path, f"Wikimedia Commons{' / ' + artist[:60] if artist else ''}")
        return None

    def pixabay(self, query: str, out: Path) -> FoundImage | None:
        r = self.http.get("https://pixabay.com/api/", params={"key": self.pixabay_key, "q": query[:100],
                                                             "image_type": "photo", "safesearch": "true"})
        r.raise_for_status()
        for hit in r.json().get("hits", [])[:5]:
            path = self._save(hit["largeImageURL"], out)
            if path:
                return FoundImage(path, "Pixabay")
        return None

    def ai(self, prompt: str, out: Path) -> FoundImage | None:
        from openai import OpenAI

        resp = OpenAI().images.generate(model="gpt-image-1", size="1024x1536",
                                        prompt=f"{prompt}. Photorealistic, dramatic lighting, dark background, no text.")
        path = out.with_suffix(".png")
        path.write_bytes(base64.b64decode(resp.data[0].b64_json))
        return FoundImage(path, "AI tasvir")

    # ------------------------------------------------------------- asosiy
    def find(self, image_source: str, query: str, prompt: str, out: Path) -> FoundImage | None:
        attempts = []
        if image_source == "source_article":
            attempts.append(("manba", lambda: self.source_article(out)))
        if self.category in ("Koinot", "Ilm-fan"):
            attempts.append(("nasa", lambda: self.nasa(query, out)))
        attempts.append(("wikimedia", lambda: self.wikimedia(query, out)))
        if image_source != "source_article":
            attempts.append(("manba", lambda: self.source_article(out)))
        if self.ai_images:
            attempts.append(("ai", lambda: self.ai(prompt, out)))
        if self.stock_fallback and self.pixabay_key:
            attempts.append(("pixabay", lambda: self.pixabay(query, out)))
        for name, fn in attempts:
            try:
                found = fn()
                if found:
                    log.info("Rasm (%s): %s", name, query)
                    if found.credit not in self.credits:
                        self.credits.append(found.credit)
                    return found
            except Exception as e:
                log.warning("Rasm topilmadi (%s, %s): %s", name, query, e)
        return None
