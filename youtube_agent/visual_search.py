"""E. Vizual qidiruv: har sahna uchun aynan aytilayotgan gapni ko'rsatadigan kadrni topadi.

Tartib (sahnaning visual_source_type'iga qarab boshlanadi, keyin kengayadi):
  stok-video (Pexels, Pixabay) -> ilmiy/ta'limiy arxiv (Wikimedia Commons) -> yangilik sahifasi rasmi
  -> rasm (Wikimedia, Pixabay) -> AI video (yoqilgan bo'lsa) -> generatsiya qilingan grafika.

Har nomzod: texnik filtr (o'lcham, davomiylik, takror) -> yuklab olish va ffprobe -> AI ko'zi bilan kadrlarni
tekshirish (sarlavhaga emas, kadrning o'ziga qaraladi). Aloqasiz kadr jimgina qo'yilmaydi: hech narsa topilmasa,
sahna faktini ko'rsatuvchi grafika yasaladi.
"""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass, field
from html import unescape
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

from .categories import render_prompt
from .graphics import render_graphic
from .jobs import retry
from .llm import LLM
from .net import http_client
from .media import MediaError, average_hash, extract_frames, hash_distance, probe
from .schemas import AssetMeta, Scene, VisualCheckDraft
from .video_generator import VideoGenerator

log = logging.getLogger(__name__)
UA = {"User-Agent": "UzScienceShorts/1.0 (educational; contact via YouTube channel)"}
FREE_LICENSE_RE = re.compile(r"^(cc0|public domain|pd|cc by(-sa)? [\d.]+|cc-by(-sa)?-[\d.]+|attribution)", re.I)
MAX_DOWNLOAD = 120 * 1024 * 1024


@dataclass
class Candidate:
    provider: str
    asset_id: str
    media_type: str  # video | image
    url: str
    page_url: str = ""
    width: int = 0
    height: int = 0
    duration: float = 0.0
    creator: str = ""
    license: str = ""
    license_url: str = ""
    license_verified: bool = False
    query: str = ""

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.asset_id}"


@dataclass
class VisualSettings:
    pexels_key: str = ""
    pixabay_key: str = ""
    allow_publisher_images: bool = True
    vision_check: bool = True
    min_relevance: float = 6.0
    fallback_relevance: float = 4.0  # aniq kadr topilmasa: umumiy mavzuga mos (masalan "AI data center") kadr
    max_checks_per_scene: int = 4
    font_bold: str = ""
    font_regular: str = ""


# ------------------------------------------------------------------ provayderlar
class Providers:
    def __init__(self, s: VisualSettings, http: httpx.Client | None = None):
        self.s = s
        self.http = http or http_client(30, UA)
        self._og_cache: dict[str, str | None] = {}

    def _get(self, url: str, **params) -> dict:
        r = retry(lambda: self.http.get(url, params=params), attempts=2, what=urlparse(url).netloc)
        r.raise_for_status()
        return r.json()

    # Pexels: https://www.pexels.com/api/documentation/
    def pexels_video(self, q: str) -> list[Candidate]:
        if not self.s.pexels_key:
            return []
        r = retry(lambda: self.http.get("https://api.pexels.com/videos/search", headers={"Authorization": self.s.pexels_key},
                                        params={"query": q, "orientation": "portrait", "per_page": 15}), attempts=2)
        r.raise_for_status()
        out = []
        for v in r.json().get("videos", []):
            files = [f for f in v.get("video_files", []) if f.get("link") and (f.get("height") or 0) >= 720]
            if not files:
                continue
            f = min(files, key=lambda f: abs((f.get("height") or 0) - 1920))
            out.append(Candidate("Pexels", str(v["id"]), "video", f["link"], v.get("url", ""), f.get("width") or 0,
                                 f.get("height") or 0, float(v.get("duration") or 0), (v.get("user") or {}).get("name", ""),
                                 "Pexels License", "https://www.pexels.com/license/", True, q))
        return out

    # Pixabay: https://pixabay.com/api/docs/
    def pixabay_video(self, q: str) -> list[Candidate]:
        if not self.s.pixabay_key:
            return []
        out = []
        for hit in self._get("https://pixabay.com/api/videos/", key=self.s.pixabay_key, q=q[:100],
                             per_page=20, safesearch="true").get("hits", []):
            files = [f for f in (hit.get("videos") or {}).values() if f.get("url") and (f.get("height") or 0) >= 720]
            if not files:
                continue
            f = min(files, key=lambda f: abs(f["height"] - 1920) if f["height"] >= f["width"] else abs(f["height"] - 1080))
            out.append(Candidate("Pixabay", str(hit["id"]), "video", f["url"], hit.get("pageURL", ""), f["width"],
                                 f["height"], float(hit.get("duration") or 0), hit.get("user", ""),
                                 "Pixabay Content License", "https://pixabay.com/service/license-summary/", True, q))
        return out

    def pixabay_image(self, q: str) -> list[Candidate]:
        if not self.s.pixabay_key:
            return []
        out = []
        for hit in self._get("https://pixabay.com/api/", key=self.s.pixabay_key, q=q[:100], image_type="photo",
                             per_page=20, safesearch="true").get("hits", []):
            out.append(Candidate("Pixabay", str(hit["id"]), "image", hit["largeImageURL"], hit.get("pageURL", ""),
                                 hit.get("imageWidth", 0), hit.get("imageHeight", 0), 0.0, hit.get("user", ""),
                                 "Pixabay Content License", "https://pixabay.com/service/license-summary/", True, q))
        return out

    # Wikimedia Commons: https://www.mediawiki.org/wiki/API:Search
    def _wikimedia(self, q: str, filetype: str, media_type: str) -> list[Candidate]:
        data = self._get("https://commons.wikimedia.org/w/api.php", action="query", format="json", generator="search",
                         gsrnamespace=6, gsrsearch=f"{q} filetype:{filetype}", gsrlimit=10, prop="imageinfo",
                         iiprop="url|mime|size|extmetadata", iiurlwidth=1600)
        pages = sorted((data.get("query") or {}).get("pages", {}).values(), key=lambda p: p.get("index", 99))
        out = []
        for p in pages:
            info = (p.get("imageinfo") or [{}])[0]
            meta = info.get("extmetadata") or {}
            lic = (meta.get("LicenseShortName") or {}).get("value", "")
            artist = re.sub("<[^>]+>", "", (meta.get("Artist") or {}).get("value", "")).strip()[:80]
            url = info.get("url", "") if media_type == "video" else (info.get("thumburl") or info.get("url", ""))
            if not url:
                continue
            out.append(Candidate("Wikimedia Commons", str(p.get("pageid")), media_type, url,
                                 info.get("descriptionurl", ""), info.get("width", 0), info.get("height", 0),
                                 float(info.get("duration") or 0), artist, lic,
                                 (meta.get("LicenseUrl") or {}).get("value", ""), bool(FREE_LICENSE_RE.match(lic)), q))
        return out

    def wikimedia_video(self, q: str) -> list[Candidate]:
        return self._wikimedia(q, "video", "video")

    def wikimedia_image(self, q: str) -> list[Candidate]:
        return [c for c in self._wikimedia(q, "bitmap", "image")]

    # Yangilik sahifasining asosiy rasmi (og:image) - huquqi tekshirilmagan, QA'da ogohlantiriladi
    def publisher_images(self, page_urls: list[str]) -> list[Candidate]:
        if not self.s.allow_publisher_images:
            return []
        out = []
        for page in page_urls[:6]:
            if page not in self._og_cache:
                try:
                    html = self.http.get(page).text[:400_000]
                    m = (re.search(r'<meta[^>]+(?:property|name)=["\'](?:og:image|twitter:image)["\'][^>]+content=["\']([^"\']+)', html, re.I)
                         or re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\'](?:og:image|twitter:image)["\']', html, re.I))
                    self._og_cache[page] = urljoin(page, unescape(m.group(1))) if m else None
                except httpx.HTTPError as e:
                    log.debug("og:image olinmadi %s: %s", page, e)
                    self._og_cache[page] = None
            img = self._og_cache[page]
            if img:
                site = urlparse(page).netloc.removeprefix("www.")
                out.append(Candidate(site, img, "image", img, page, creator=site,
                                     license="publisher image - rights not verified", license_verified=False))
        return out


CHAINS = {
    "stock_video": ["pexels_video", "pixabay_video", "wikimedia_video"],
    "archival_footage": ["wikimedia_video", "pexels_video", "pixabay_video"],
    "source_image": ["publisher", "wikimedia_image", "pixabay_image"],
    "still_image": ["wikimedia_image", "pixabay_image", "publisher"],
    "graphic": [],
    "ai_video": [],
}
ALL_PROVIDERS = ["pexels_video", "pixabay_video", "wikimedia_video", "publisher", "wikimedia_image", "pixabay_image"]


@dataclass
class SceneSearchLog:
    scene_id: int
    tried: list[dict] = field(default_factory=list)


class VisualSearcher:
    def __init__(self, settings: VisualSettings, llm: LLM | None = None, video_gen: VideoGenerator | None = None,
                 providers: Providers | None = None):
        self.s = settings
        self.llm = llm
        self.video_gen = video_gen
        self.p = providers or Providers(settings)
        self.used_keys: set[str] = set()
        self.used_hashes: list[str] = []
        self._lock = threading.Lock()  # sahnalar parallel qidirilganda takrorni oldini olish
        self.budget_ok = lambda: True    # orkestrator pul chegarasini shu orqali beradi

    # --------------------------------------------------------------- yordamchi
    def _search(self, name: str, query: str, page_urls: list[str]) -> list[Candidate]:
        if name == "publisher":
            return self.p.publisher_images(page_urls)
        return getattr(self.p, name)(query)

    @staticmethod
    def technical_score(c: Candidate, need_seconds: float) -> float | None:
        """None - nomzod yaroqsiz. Aks holda: vertikal, sifatli, yetarli uzun kadrlar yuqoriroq."""
        short = min(c.width, c.height) if c.width and c.height else 0
        if c.media_type == "video":
            if short and short < 540:
                return None
            if c.duration and c.duration < min(need_seconds * 0.5, 3.0):
                return None
        elif short and short < 600:
            return None
        score = 0.0
        if c.width and c.height:
            score += 2.0 if c.height >= c.width else 0.0  # vertikal afzal
            score += min(short / 1080, 1.0)
        if c.media_type == "video":
            score += 1.5 + (0.5 if c.duration >= need_seconds else 0)
        if c.license_verified:
            score += 0.5
        return score

    def _download(self, c: Candidate, out_base: Path) -> Path:
        ext = ".mp4" if c.media_type == "video" else ".jpg"
        if c.media_type == "video" and re.search(r"\.(webm|ogv|ogg)(\?|$)", c.url, re.I):
            ext = ".webm"
        out = out_base.with_suffix(ext)
        with self.p.http.stream("GET", c.url) as r:
            r.raise_for_status()
            size = 0
            with open(out, "wb") as f:
                for chunk in r.iter_bytes(1 << 16):
                    size += len(chunk)
                    if size > MAX_DOWNLOAD:
                        raise MediaError("fayl juda katta")
                    f.write(chunk)
        if c.media_type == "image":  # har xil formatlarni JPEG'ga keltiramiz
            from PIL import Image
            img = Image.open(out).convert("RGB")
            img.save(out, quality=92)
        return out

    def _check_relevance(self, scene: Scene, frames: list[Path], query: str) -> VisualCheckDraft:
        prompt = render_prompt("visual_check", voiceover=scene.voiceover_text, description=scene.visual_description,
                               criteria=scene.relevance_criteria or scene.visual_description, query=query)
        return self.llm.parse(prompt, VisualCheckDraft, effort="low", images=frames, cheap=True)

    def _vision(self) -> bool:
        return bool(self.llm and self.s.vision_check and self.budget_ok())

    def _is_duplicate(self, fp: str) -> bool:
        return any(hash_distance(fp, h) <= 6 for h in self.used_hashes)

    # ------------------------------------------------------------------- asosiy
    def find(self, scene: Scene, scene_dir: Path, page_urls: list[str], palette: int = 0,
             skip_keys: set[str] | None = None, fallback_title: str = "") -> tuple[AssetMeta, SceneSearchLog]:
        scene_dir.mkdir(parents=True, exist_ok=True)
        best: dict = {}  # shu sahna uchun zaxira kadr (parallel sahnalar aralashmasligi uchun lokal)
        slog = SceneSearchLog(scene.id)
        skip = set(skip_keys or ())
        need = scene.estimated_duration
        chain = CHAINS.get(scene.visual_source_type, []) + [p for p in ALL_PROVIDERS
                                                             if p not in CHAINS.get(scene.visual_source_type, [])]
        if scene.visual_source_type == "graphic":
            chain = []
        checks = 0
        if scene.visual_source_type == "ai_video" and self.video_gen and scene.video_generation_prompt:
            asset = self._ai_video(scene, scene_dir, slog)
            if asset:
                return asset, slog
        for name in chain:
            queries = scene.visual_search_queries if name != "publisher" else [""]
            for q in queries:
                try:
                    cands = self._search(name, q, page_urls)
                except Exception as e:  # tarmoq/API xatosi - keyingi provayderga o'tamiz
                    slog.tried.append({"provider": name, "query": q, "error": str(e)[:200]})
                    continue
                scored = []
                for c in cands:
                    if c.key in self.used_keys or c.key in skip:
                        continue
                    sc = self.technical_score(c, need)
                    if sc is not None:
                        scored.append((sc, c))
                scored.sort(key=lambda x: -x[0])
                slog.tried.append({"provider": name, "query": q, "found": len(cands), "usable": len(scored)})
                for _, c in scored[:2]:
                    if self._vision() and checks >= self.s.max_checks_per_scene:
                        break
                    asset = self._try_candidate(scene, c, scene_dir, slog, best)
                    checks += 1
                    if asset:
                        return asset, slog
            if self._vision() and checks >= self.s.max_checks_per_scene:
                break
        if self.video_gen and scene.video_generation_prompt and scene.visual_source_type != "ai_video":
            asset = self._ai_video(scene, scene_dir, slog)
            if asset:
                return asset, slog
        fb = best.get("meta")
        if fb and self._claim(fb):
            fb.relevance_reason = f"aniq kadr topilmadi, umumiy mavzuga mos: {fb.relevance_reason}"
            slog.tried.append({"fallback": f"{fb.provider}:{fb.asset_id}", "score": fb.relevance_score})
            return fb, slog
        return self._graphic(scene, scene_dir, palette, fallback_title), slog

    def _try_candidate(self, scene: Scene, c: Candidate, scene_dir: Path, slog: SceneSearchLog,
                       best: dict | None = None) -> AssetMeta | None:
        entry = {"candidate": c.key, "query": c.query}
        slog.tried.append(entry)
        try:
            path = self._download(c, scene_dir / f"cand_{re.sub(r'[^A-Za-z0-9]+', '_', c.asset_id)[-40:]}")
            info = probe(path)
            if c.media_type == "video" and (not info.has_video or info.duration < 1.0):
                raise MediaError("video oqimi yo'q yoki juda qisqa")
            frames = extract_frames(path, scene_dir / "frames" / c.asset_id[-20:].replace("/", "_"), count=3)
            fp = average_hash(frames[len(frames) // 2])
            if self._is_duplicate(fp):
                entry["rejected"] = "takroriy kadr"
                return None
            score, reason = None, ""
            if self._vision():
                verdict = self._check_relevance(scene, frames, c.query)
                score, reason = verdict.score, verdict.reason
                entry.update(score=score, reason=reason[:200])
                if not verdict.matches or verdict.score < self.s.min_relevance:
                    entry["rejected"] = "mos emas"
                    if best is not None and verdict.score >= self.s.fallback_relevance:
                        if "meta" not in best or verdict.score > (best["meta"].relevance_score or 0):
                            # zaxira: aniq kadr topilmasa ishlatiladi
                            best["meta"] = self._meta(scene, c, path, info, verdict.score, reason, fp)
                    return None
            meta = self._meta(scene, c, path, info, score, reason, fp)
            return meta if self._claim(meta) else self._dup(entry)
        except Exception as e:
            entry["error"] = str(e)[:200]
            return None

    @staticmethod
    def _dup(entry: dict) -> None:
        entry["rejected"] = "takroriy kadr"
        return None

    def _claim(self, meta: AssetMeta) -> bool:
        """Kadrni band qiladi (parallel sahnalar bir xil kadrni olmasligi uchun)."""
        key = f"{meta.provider}:{meta.asset_id}"
        with self._lock:
            if key in self.used_keys or self._is_duplicate(meta.fingerprint):
                return False
            self.used_keys.add(key)
            self.used_hashes.append(meta.fingerprint)
            return True

    @staticmethod
    def _meta(scene: Scene, c: Candidate, path: Path, info, score, reason: str, fp: str) -> AssetMeta:
        return AssetMeta(scene_id=scene.id, provider=c.provider, asset_id=c.asset_id, media_type=c.media_type,
                         source_url=c.url, page_url=c.page_url, creator=c.creator, license=c.license,
                         license_url=c.license_url, license_verified=c.license_verified, query=c.query,
                         local_path=str(path), width=info.width, height=info.height, duration=info.duration,
                         relevance_score=score, relevance_reason=reason, fingerprint=fp)

    def _ai_video(self, scene: Scene, scene_dir: Path, slog: SceneSearchLog) -> AssetMeta | None:
        try:
            gen = self.video_gen.generate_scene_video(scene.video_generation_prompt, scene.estimated_duration,
                                                      scene_dir / "ai_video.mp4")
        except Exception as e:
            slog.tried.append({"provider": "ai_video", "error": str(e)[:200]})
            return None
        info = probe(gen.path)
        return AssetMeta(scene_id=scene.id, provider=gen.provider, asset_id=gen.job_id, media_type="video",
                         license=f"AI-generated ({gen.model})", license_verified=True, ai_generated=True,
                         query=scene.video_generation_prompt or "", local_path=str(gen.path), width=info.width,
                         height=info.height, duration=info.duration, cost_usd=gen.cost_usd,
                         relevance_reason="AI tomonidan sahna tavsifi bo'yicha yaratilgan")

    def _graphic(self, scene: Scene, scene_dir: Path, palette: int, fallback_title: str = "") -> AssetMeta:
        # matn subtitrda bor - grafikada faqat asosiy raqam/kalit so'z va qisqa izoh (takrorlanmaydi)
        title = scene.on_screen_text or fallback_title
        sub = scene.on_screen_subtext if scene.on_screen_text else ""
        out = render_graphic(title, sub, "", scene_dir / "graphic.jpg", self.s.font_bold, self.s.font_regular, palette)
        return AssetMeta(scene_id=scene.id, provider="generated", asset_id=f"graphic-{scene.id}", media_type="graphic",
                         license="generated", license_verified=True, local_path=str(out), width=1080, height=1920,
                         relevance_reason="sahna faktini ko'rsatuvchi grafika (mos kadr topilmadi yoki grafika rejalashtirilgan)")
