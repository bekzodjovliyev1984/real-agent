"""D. Storyboard: ssenariy sahnalarga bo'linadi, har sahnaga aniq vizual reja beriladi."""

from __future__ import annotations

import difflib
import logging
import re

from .categories import render_prompt
from .llm import LLM
from .schemas import Claim, Scene, ScriptDraft, ShortPlan, StoryboardDraft, TopicDraft
from .script_agent import WORDS_PER_SECOND, claims_block, word_count

log = logging.getLogger(__name__)


def _norm(text: str) -> str:
    return re.sub(r"[^\w]+", " ", text.lower()).strip()


def build_plan(draft: StoryboardDraft, script: ScriptDraft, topic: TopicDraft, claims: list[Claim],
               category: str, ai_video_enabled: bool) -> ShortPlan:
    beats_text = " ".join(b.text for b in script.beats)
    scenes_text = " ".join(s.voiceover_text for s in draft.scenes)
    ratio = difflib.SequenceMatcher(None, _norm(beats_text), _norm(scenes_text)).ratio()
    if ratio < 0.9:
        raise ValueError(f"sahnalardagi diktor matni ssenariydan farq qiladi (o'xshashlik {ratio:.2f}). "
                         "Ssenariy matnini o'zgartirmasdan, to'liq va tartib bilan sahnalarga bo'l.")
    scenes = []
    for i, d in enumerate(draft.scenes, 1):
        if any(ch.isdigit() for ch in d.voiceover_text):
            raise ValueError(f"sahna {i}: diktor matnida raqam belgisi bor - so'z bilan yoz")
        source = d.visual_source_type
        if source == "graphic" and not d.on_screen_text.strip():
            raise ValueError(f"sahna {i}: graphic turidagi sahnada on_screen_text (raqam yoki kalit so'z) bo'lishi shart")
        if source == "ai_video" and not ai_video_enabled:
            source = "graphic" if d.on_screen_text.strip() else "stock_video"
        # davomiylikni so'z soniga qarab qayta hisoblaymiz (AI taxmini ko'pincha noto'g'ri)
        est = max(1.5, round(word_count(d.voiceover_text) / WORDS_PER_SECOND + 0.2, 1))
        scenes.append(Scene(
            id=i, voiceover_text=d.voiceover_text, subtitle_text=d.subtitle_text,
            estimated_duration=min(est, 20.0), visual_description=d.visual_description,
            visual_purpose=d.visual_purpose, visual_source_type=source,
            visual_search_queries=[q for q in d.visual_search_queries if q.strip()][:4] or [d.visual_description[:60]],
            video_generation_prompt=d.video_generation_prompt.strip() or None,
            on_screen_text=d.on_screen_text.strip(), on_screen_subtext=d.on_screen_subtext.strip(),
            sound_effect=d.sound_effect, transition=d.transition,
            related_claim_ids=d.related_claim_ids, relevance_criteria=d.relevance_criteria,
        ))
    total = sum(s.estimated_duration for s in scenes)
    return ShortPlan(
        title=script.title, category=category, topic=topic.topic,
        target_duration_seconds=min(max(total, 15.0), 60.0), hook_type=script.hook_type, hook=script.hook,
        description=script.description, tags=script.tags[:15], music_mood=script.music_mood,
        claims=claims, scenes=scenes,
    )


def build_storyboard(llm: LLM, category: str, topic: TopicDraft, script: ScriptDraft, claims: list[Claim],
                     ai_video_enabled: bool = False) -> ShortPlan:
    beats = "\n".join(f"{i}. [{b.purpose}] {b.text}  (da'volar: {', '.join(b.claim_ids) or '-'})"
                      for i, b in enumerate(script.beats, 1))
    total_words = sum(word_count(b.text) for b in script.beats)
    approx = total_words / WORDS_PER_SECOND
    prompt = render_prompt("storyboard", beats=beats, claims=claims_block(claims),
                           min_scenes=max(3, int(approx / 6)), max_scenes=max(4, int(approx / 2.5)))
    plan = llm.parse_validated(prompt, StoryboardDraft,
                               lambda d: build_plan(d, script, topic, claims, category, ai_video_enabled),
                               effort="medium")
    log.info("Storyboard: %d sahna, ~%.0fs", len(plan.scenes), plan.target_duration_seconds)
    return plan
