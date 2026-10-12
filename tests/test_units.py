"""Tarmoqsiz unit testlar: sxemalar, matn, subtitrlar, fakt-tekshiruv, ssenariy, vizual tanlov, retry."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from fakes import BEATS, FONT, FONT_BOLD, FakeLLM, FakeProviders, FakeSearcher, make_media
from youtube_agent.fact_checker import to_claims
from youtube_agent.jobs import Job, retry
from youtube_agent.render import XFADE, scene_durations, video_framing_filter
from youtube_agent.schemas import (BeatDraft, Claim, ClaimDraft, FactCheckDraft, JobState, Scene, ScriptDraft,
                                   ShortPlan, SourceDraft, SourceRef, VerificationStatus, WordTiming)
from youtube_agent.script_agent import validate_script
from youtube_agent.speech import number_to_words, prepare_speech
from youtube_agent.storyboard_agent import build_plan
from youtube_agent.subtitles import align, build_ass, chunk, display_words, parse_ass_events, scene_bounds, tokens
from youtube_agent.tts import apply_pronunciation, split_for_tts
from youtube_agent.visual_search import Candidate, VisualSearcher, VisualSettings


def _scene(i, dur=5.0, **kw):
    base = dict(id=i, voiceover_text=f"Sahna {i} matni bu yerda", subtitle_text=f"Sahna {i} matni",
                estimated_duration=dur, visual_description="aniq kadr tavsifi", visual_source_type="stock_video",
                visual_search_queries=["electric car"], related_claim_ids=["claim_01"])
    base.update(kw)
    return Scene(**base)


def _claim(cid="claim_01", status="verified"):
    return Claim(id=cid, claim="fakt", status=status,
                 sources=[SourceRef(title="t", url="https://example.org/a")] if status in ("verified", "qualified") else [])


def _plan(scenes=None, claims=None, **kw):
    kw.setdefault("target_duration_seconds", 30)
    return ShortPlan(title="Sinov sarlavha #shorts", category="Ilm-fan", topic="t", hook_type="question", hook="h",
                     claims=claims or [_claim()], scenes=scenes or [_scene(1), _scene(2), _scene(3), _scene(4)], **kw)


# ----------------------------------------------------------------- sxemalar
def test_plan_valid():
    assert len(_plan().scenes) == 4


def test_plan_requires_three_scenes():
    with pytest.raises(ValidationError):
        _plan(scenes=[_scene(1, 10), _scene(2, 10)])


def test_plan_scene_ids_sequential():
    with pytest.raises(ValidationError, match="ketma-ket"):
        _plan(scenes=[_scene(1), _scene(3), _scene(4)])


def test_plan_duration_bounds():
    with pytest.raises(ValidationError, match="davomiyligi"):
        _plan(scenes=[_scene(1, 2), _scene(2, 2), _scene(3, 2)])
    with pytest.raises(ValidationError):
        _plan(target_duration_seconds=90)


def test_plan_unknown_claim_and_empty_narration():
    with pytest.raises(ValidationError, match="noma'lum da'vo"):
        _plan(scenes=[_scene(1), _scene(2), _scene(3, related_claim_ids=["claim_09"])])
    with pytest.raises(ValidationError):
        _scene(1, voiceover_text="   ")


def test_verified_claim_needs_source_and_valid_url():
    with pytest.raises(ValidationError):
        Claim(id="claim_01", claim="x", status="verified", sources=[])
    with pytest.raises(ValidationError):
        SourceRef(title="t", url="not a url")
    with pytest.raises(ValidationError):
        Claim(id="c1", claim="x", status="unverified")


def test_publication_blockers():
    plan = _plan(claims=[_claim(), _claim("claim_02", "unverified")],
                 scenes=[_scene(1), _scene(2), _scene(3, related_claim_ids=["claim_02"])])
    blockers = plan.publication_blockers()
    assert len(blockers) == 1 and "sahna 3" in blockers[0]


# ----------------------------------------------------------- nutq uchun matn
def test_numbers_and_apostrophes():
    assert number_to_words(1977) == "ming toʻqqiz yuz yetmish yetti"
    assert number_to_words(1_001_000) == "bir million bir ming"
    out = prepare_speech("Narxi 25% ga tushdi, 1977-yilda og'ir ma'lumot 4,3 mln.")
    assert "yigirma besh foizga" in out and "yettinchi yilda" in out
    assert "ogʻir" in out and "maʼlumot" in out and "toʻrt butun oʻndan uch million" in out
    assert not any(ch.isdigit() for ch in out)


def test_pronunciation_dictionary_whole_words():
    m = {"GPT": "Ji Pi Ti", "ChatGPT": "Chat Ji Pi Ti"}
    assert apply_pronunciation("ChatGPT va GPT, lekin GPTX emas", m) == "Chat Ji Pi Ti va Ji Pi Ti, lekin GPTX emas"


def test_split_for_tts():
    parts = split_for_tts("Birinchi gap. " * 400, limit=500)
    assert all(len(p) <= 500 for p in parts) and len(parts) > 1


# ------------------------------------------------------------------ subtitr
def test_alignment_handles_asr_mismatch():
    toks = tokens("Olimlar yangi model chiqardi va u ikki baravar tez.")
    asr = [WordTiming(text=t, start=i * 0.5, end=i * 0.5 + 0.4) for i, t in
           enumerate("olimlar yangi modul chiqardi u ikki barobar tez".split())]
    out = align(toks, asr, 5.0)
    assert [w.text for w in out] == toks
    assert all(b.start >= a.start for a, b in zip(out, out[1:]))
    assert out[0].start == 0.0 and out[-1].start == 3.5


def test_scene_bounds_and_display_words():
    words = [WordTiming(text=f"w{i}", start=i * 0.5, end=i * 0.5 + 0.4) for i in range(10)]
    b = scene_bounds([4, 6], words, 6.0)
    assert b[0] == 0 and b[-1] == 6.0 and 1.8 < b[1] < 2.0
    spoken = [words[:4], words[4:]]
    dw = display_words(["w0 w1 w2 w3", "w4 5x w7 w8 w9"], spoken, [set(), set()])
    assert dw[0].start == 0.0 and dw[4].start == 2.0
    assert any(w.emphasis for w in dw if w.text == "5x")
    ch = chunk(dw)
    assert all(len(c) <= 4 for c in ch) and all(len({w.scene_id for w in c}) == 1 for c in ch)


def test_ass_roundtrip_and_no_overlap():
    words = [WordTiming(text=t, start=i * 0.4, end=i * 0.4 + 0.3) for i, t in enumerate("Bu ogʻir maʼlumot".split())]
    dw = display_words(["Bu ogʻir maʼlumot"], [words], [set()])
    ass = build_ass(chunk(dw), __import__("youtube_agent.subtitles", fromlist=["SubtitleStyle"]).SubtitleStyle(), 2.0)
    ev = parse_ass_events(ass)
    assert ev and all(e <= 2.0 for _, e, _ in ev) and "og‘ir" in ev[0][2]
    assert all(ev[i][1] <= ev[i + 1][0] + 1e-6 for i in range(len(ev) - 1))


# ------------------------------------------------------------- fakt-tekshiruv
def _fc(urls, status="verified"):
    return FactCheckDraft(claims=[ClaimDraft(id="claim_01", claim="x", status=status, qualification="",
                                             sources=[SourceDraft(title="t", url=u, excerpt="e") for u in urls])])


def test_fact_check_drops_invented_and_dead_urls():
    evidence = "dalil: https://real.org/page"
    claims = to_claims(_fc(["https://real.org/page", "https://invented.org/x"]), ["claim_01"], evidence, lambda u: True)
    assert claims[0].status == VerificationStatus.verified and len(claims[0].sources) == 1
    dead = to_claims(_fc(["https://real.org/page"]), ["claim_01"], evidence, lambda u: False)
    assert dead[0].status == VerificationStatus.unverified and not dead[0].sources


def test_fact_check_rejects_unknown_ids_and_marks_missing():
    with pytest.raises(ValueError):
        to_claims(_fc([]), ["claim_02"], "", lambda u: True)
    out = to_claims(FactCheckDraft(claims=[]), ["claim_01"], "", lambda u: True)
    assert out[0].status == VerificationStatus.unverified


# ------------------------------------------------------- ssenariy / storyboard
def _script(beats=None):
    return ScriptDraft(title="Sarlavha", hook_type="question", hook="h", description="d", tags=[], music_mood="calm",
                       beats=beats or [BeatDraft(purpose=p, text=t, claim_ids=c) for p, t, c in BEATS])


def test_validate_script_rules():
    ok = validate_script(_script(), {"claim_01", "claim_02", "claim_03", "claim_04"}, 40, 120)
    assert ok.title.endswith("#shorts")
    with pytest.raises(ValueError, match="raqam"):
        validate_script(_script([BeatDraft(purpose="hook", text="10 daqiqa", claim_ids=[]),
                                 BeatDraft(purpose="payoff", text="tamom", claim_ids=[])]), set(), 1, 100)
    with pytest.raises(ValueError, match="tasdiqlanmagan"):
        validate_script(_script(), {"claim_01"}, 40, 120)
    with pytest.raises(ValueError, match="so'z"):
        validate_script(_script(), {"claim_01", "claim_02", "claim_03", "claim_04"}, 200, 300)


def test_storyboard_must_keep_script_text():
    llm = FakeLLM()
    from youtube_agent.schemas import StoryboardDraft, TopicDraft
    draft = llm.parse("", StoryboardDraft)
    topic = llm.parse("", TopicDraft)
    claims = [_claim(f"claim_0{i}") for i in range(1, 5)]
    plan = build_plan(draft, _script(), topic, claims, "Ilm-fan", ai_video_enabled=False)
    assert len(plan.scenes) == 5
    draft.scenes[1].voiceover_text = "Butunlay boshqa, o'ylab topilgan gap"
    draft.scenes[2].voiceover_text = "Yana bir boshqa gap"
    with pytest.raises(ValueError, match="farq qiladi"):
        build_plan(draft, _script(), topic, claims, "Ilm-fan", ai_video_enabled=False)


# --------------------------------------------------------------- vizual tanlov
def test_technical_score_filters():
    good = Candidate("P", "1", "video", "u", width=1080, height=1920, duration=10)
    land = Candidate("P", "2", "video", "u", width=1920, height=1080, duration=10)
    tiny = Candidate("P", "3", "video", "u", width=320, height=568, duration=10)
    short = Candidate("P", "4", "video", "u", width=1080, height=1920, duration=1)
    s = VisualSearcher.technical_score
    assert s(good, 5) > s(land, 5) and s(tiny, 5) is None and s(short, 5) is None


def test_visual_rejects_irrelevant_and_falls_back_to_graphic(tmp_path):
    media = make_media(tmp_path / "m")
    llm = FakeLLM(visual_score=2.0)  # AI ko'zi: kadrlar mos emas
    vs = VisualSettings(vision_check=True, font_bold=FONT_BOLD, font_regular=FONT, max_checks_per_scene=3)
    searcher = FakeSearcher(vs, llm, None, FakeProviders(media))
    asset, slog = searcher.find(_scene(1, on_screen_text="10 DAQIQA"), tmp_path / "s1", [], fallback_title="Mavzu")
    assert asset.media_type == "graphic" and asset.license == "generated"
    assert any(t.get("rejected") == "mos emas" for t in slog.tried)


def test_visual_dedupes_same_footage(tmp_path):
    media = make_media(tmp_path / "m")
    vs = VisualSettings(vision_check=False, font_bold=FONT_BOLD, font_regular=FONT)
    searcher = FakeSearcher(vs, None, None, FakeProviders(media))
    a1, _ = searcher.find(_scene(1), tmp_path / "s1", [])
    a2, _ = searcher.find(_scene(2), tmp_path / "s2", [])
    assert a1.fingerprint != a2.fingerprint


# ------------------------------------------------------------------ montaj
def test_framing_never_stretches():
    assert "crop=1080:1920" in video_framing_filter(1080, 1920)
    land = video_framing_filter(1920, 1080)
    assert "boxblur" in land and "overlay" in land


def test_crossfade_durations_keep_sync():
    scenes = [_scene(1), _scene(2, transition="crossfade"), _scene(3)]
    bounds = [0.0, 5.0, 10.0, 15.0]
    d = scene_durations(bounds, scenes)
    assert d[0] == pytest.approx(5 + XFADE) and d[1] == pytest.approx(5.04) and d[2] == pytest.approx(5.0)


# ------------------------------------------------------------------ yordamchi
def test_retry_is_bounded(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    calls = []

    def boom():
        calls.append(1)
        raise ConnectionError("x")
    with pytest.raises(ConnectionError):
        retry(boom, attempts=3)
    assert len(calls) == 3
    assert retry(lambda: 5, attempts=2) == 5


def test_job_state_persists(tmp_path):
    job = Job.create(tmp_path, "Ilm-fan")
    job.set_state(JobState.researched, "x")
    job.write("plan.json", {"a": 1})
    again = Job.load(tmp_path, job.id)
    assert again.state == JobState.researched and again.read_json("plan.json") == {"a": 1}
    assert again.meta["history"][-1]["state"] == "researched"


def test_all_prompts_render():
    from youtube_agent.categories import PROMPTS_DIR, render_prompt
    from youtube_agent.content import draft_comment_reply
    import re as _re
    for f in PROMPTS_DIR.glob("*.md"):
        names = set(_re.findall(r"\$(\w+)", f.read_text("utf-8")))
        assert render_prompt(f.stem, **{n: "x" for n in names})
    llm = FakeLLM()
    llm.parse = lambda prompt, schema, **k: schema(should_reply=False, reply="", reason=prompt[:10])
    assert draft_comment_reply(llm, "v", "c", "a").should_reply is False


def test_dotenv_inline_comments(tmp_path, monkeypatch):
    from youtube_agent.config import load_dotenv
    env = tmp_path / ".env"
    env.write_text("\ufeffA_X=openai   # izoh\nB_X='qiymat # emas'\nC_X=Sun'iy intellekt,Ta'lim\nD_X=+0%\n", "utf-8")
    for k in ("A_X", "B_X", "C_X", "D_X"):
        monkeypatch.delenv(k, raising=False)
    load_dotenv(str(env))
    import os
    assert os.environ["A_X"] == "openai" and os.environ["B_X"] == "qiymat # emas"
    assert os.environ["C_X"] == "Sun'iy intellekt,Ta'lim" and os.environ["D_X"] == "+0%"


def test_test_mode_defaults_are_cheap(tmp_path, monkeypatch):
    from youtube_agent.config import Config
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "d"))
    for k in ("TEST_MODE", "MAX_COST_PER_VIDEO", "LLM_PROVIDER", "OPENAI_MODEL"):
        monkeypatch.delenv(k, raising=False)
    c = Config.from_env()
    assert c.test_mode and c.llm_model == "gpt-5-mini" and c.max_corrections == 0 and c.max_cost_usd == 0.30
    monkeypatch.setenv("TEST_MODE", "0")
    c = Config.from_env()
    assert c.llm_model == "gpt-5" and c.max_corrections == 2 and c.max_cost_usd == 1.0


def test_visual_uses_best_on_topic_footage_before_graphic(tmp_path):
    media = make_media(tmp_path / "m")
    llm = FakeLLM(visual_score=4.5)  # umumiy mavzuga mos, lekin aniq gapni ko'rsatmaydi
    vs = VisualSettings(vision_check=True, font_bold=FONT_BOLD, font_regular=FONT, max_checks_per_scene=3)
    searcher = FakeSearcher(vs, llm, None, FakeProviders(media))
    asset, slog = searcher.find(_scene(1), tmp_path / "s1", [])
    assert asset.media_type == "video" and asset.relevance_score == 4.5
    assert "umumiy mavzuga mos" in asset.relevance_reason and any("fallback" in t for t in slog.tried)


def test_job_root_is_absolute(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    job = Job.create(Path("rel_jobs"), "Ilm-fan")
    assert job.root.is_absolute() and job.path("render").is_absolute()
