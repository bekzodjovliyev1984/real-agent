"""Testlar uchun soxta (mock) provayderlar: tarmoq va API kalitlarisiz butun quvurni sinash."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from youtube_agent.llm import LLM
from youtube_agent.schemas import (BeatDraft, ClaimDraft, FactCheckDraft, SceneDraft, ScriptDraft,
                                   SemanticReviewDraft, SourceDraft, StoryboardDraft, TopicDraft, VisualCheckDraft,
                                   WordTiming)
from youtube_agent.tts import TTSResult
from youtube_agent.visual_search import Candidate, Providers, VisualSearcher, VisualSettings

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

URLS = ["https://www.example-lab.org/news/battery-2026", "https://www.example-uni.edu/research/solid-state",
        "https://www.example-journal.com/articles/s41586-026", "https://www.example-auto.com/press/ev-charge"]

BEATS = [
    ("hook", "Elektromobil batareyasi bor yoʻgʻi oʻn daqiqada toʻlsa, benzin quyish shoxobchalari kerak boʻlarmidi?",
     ["claim_01"]),
    ("setup", "Olimlar aynan shu savolga javob topishga yaqinlashdi va yangi qattiq batareya sinovdan oʻtdi.",
     ["claim_01"]),
    ("development", "Bu batareya ichida suyuqlik yoʻq, shuning uchun u qizib ketmaydi va yongʻin xavfi ancha past.",
     ["claim_02"]),
    ("development", "Sinovda u ming marta zaryadlangandan keyin ham sigʻimining toʻqson foizini saqlab qoldi.",
     ["claim_03"]),
    ("payoff", "Demak, yaqin yillarda zaryad kutish benzin quyishdek tez boʻlishi mumkin, lekin ommaviy ishlab "
               "chiqarish hali oldinda.", ["claim_04"]),
]


class FakeLLM(LLM):
    provider = "fake"

    def __init__(self, review_score: float = 8.5, visual_score: float = 8.0):
        super().__init__("fake-model", "fake-cheap")
        self.review_score = review_score
        self.visual_score = visual_score
        self.calls: list[str] = []

    def research(self, prompt, domains=None, effort="high"):
        self.calls.append("research")
        self._record("fake-model", 1000, 500, 2, "research")
        return "Tadqiqot. Manbalar: " + " ".join(URLS)

    def parse(self, prompt, schema, effort="medium", images=None, cheap=False):
        self.calls.append(schema.__name__)
        self._record("fake-model", 800, 300, 0, "parse")
        claims = [ClaimDraft(id=f"claim_{i:02d}", claim=f"Fakt {i}", status="verified",
                             sources=[SourceDraft(title=f"Manba {i}", url=URLS[i - 1], excerpt="iqtibos")],
                             qualification="") for i in range(1, 5)]
        if schema is TopicDraft:
            return TopicDraft(topic="Qattiq batareya", angle="zaryad tezligi", why_interesting="tez",
                              central_question="10 daqiqada zaryad mumkinmi?", visual_potential="EV zaryad",
                              claims=claims)
        if schema is FactCheckDraft:
            return FactCheckDraft(claims=claims)
        if schema is ScriptDraft:
            return ScriptDraft(title="10 daqiqada toʻladigan batareya", hook_type="question", hook=BEATS[0][1],
                               beats=[BeatDraft(purpose=p, text=t, claim_ids=c) for p, t, c in BEATS],
                               description="Yangi batareya haqida.", tags=["batareya", "elektromobil"],
                               music_mood="inspiring")
        if schema is StoryboardDraft:
            kinds = ["stock_video", "stock_video", "still_image", "graphic", "stock_video"]
            return StoryboardDraft(scenes=[SceneDraft(
                voiceover_text=t, subtitle_text=t.replace("oʻn daqiqada", "10 daqiqada"), estimated_duration=5,
                visual_description=f"sahna {i} kadri", visual_purpose="tushuntirish", visual_source_type=kinds[i],
                visual_search_queries=[f"query {i}"], video_generation_prompt="",
                on_screen_text="10 DAQIQA" if i == 0 else ("90%" if i == 3 else ""), on_screen_subtext="",
                sound_effect="none", transition="crossfade" if i == 2 else "cut", related_claim_ids=c,
                relevance_criteria="mos kadr") for i, (_, t, c) in enumerate(BEATS)])
        if schema is VisualCheckDraft:
            return VisualCheckDraft(matches=self.visual_score >= 6, score=self.visual_score, reason="test")
        if schema is SemanticReviewDraft:
            s = self.review_score
            return SemanticReviewDraft(storytelling=s, visual_relevance=s, subtitle_quality=s, factual_errors=[],
                                       visual_mismatch_issues=[] if s >= 7 else ["sahna 2 mos emas"],
                                       subtitle_issues=[], scene_ids_to_fix=[] if s >= 7 else [2],
                                       recommended_fixes=[], summary="test review")
        raise AssertionError(f"kutilmagan sxema: {schema}")


class FakeTTS:
    """Edge'ga o'xshab so'z vaqtlarini qaytaradi; ovoz o'rniga signal (boshida 0.3s jimlik)."""
    name, voice = "fake", "fake-voice"

    def synthesize(self, text: str, out: Path) -> TTSResult:
        words = text.split()
        step = 0.42
        dur = 0.3 + len(words) * step + 0.3
        out = out.with_suffix(".wav")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono:d=0.3",
                        "-f", "lavfi", "-i", f"sine=f=220:d={dur - 0.3:.2f},volume=0.4", "-filter_complex",
                        "[1]aresample=24000[s];[0][s]concat=n=2:v=0:a=1", str(out)], check=True)
        timings = [WordTiming(text=w.strip(".,?!"), start=0.3 + i * step, end=0.3 + i * step + step * 0.9)
                   for i, w in enumerate(words)]
        return TTSResult(out, timings, "fake", "fake-voice", "fake", 0.0, 0.01)


def make_media(tmp: Path) -> dict[str, Path]:
    tmp.mkdir(parents=True, exist_ok=True)
    files = {"land": tmp / "land.mp4", "port": tmp / "port.mp4", "img": tmp / "img.jpg"}
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30",
                    "-t", "8", "-pix_fmt", "yuv420p", str(files["land"])], check=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "mandelbrot=size=720x1280:rate=30",
                    "-t", "8", "-pix_fmt", "yuv420p", str(files["port"])], check=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "cellauto=s=1600x1000",
                    "-frames:v", "1", str(files["img"])], check=True)
    return files


class FakeProviders(Providers):
    def __init__(self, media: dict[str, Path]):
        super().__init__(VisualSettings())
        self.media = media
        self.n = 0

    def _cand(self, kind: str, q: str, media_type: str) -> list[Candidate]:
        self.n += 1
        path = self.media[kind]
        w, h = (1280, 720) if kind == "land" else (720, 1280) if kind == "port" else (1600, 1000)
        return [Candidate("FakeStock", f"{kind}-{self.n}", media_type, str(path), "", w, h,
                          8.0 if media_type == "video" else 0.0, "tester", "Test License", "", True, q)]

    def pexels_video(self, q):
        return self._cand("port", q, "video")

    def pixabay_video(self, q):
        return self._cand("land", q, "video")

    def wikimedia_video(self, q):
        return []

    def pixabay_image(self, q):
        return []

    def wikimedia_image(self, q):
        return self._cand("img", q, "image")

    def publisher_images(self, page_urls):
        return []


class FakeSearcher(VisualSearcher):
    def _download(self, c, out_base):
        out = out_base.with_suffix(Path(c.url).suffix)
        shutil.copy(c.url, out)
        return out
