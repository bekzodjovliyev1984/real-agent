"""Har bir video uchun alohida ish papkasi va saqlanadigan holat (qayta ishga tushirishga chidamli).

jobs/<job_id>/
  job.json          holat, urinishlar, tarix, xatolar
  job.log           batafsil log
  research.json, plan.json, assets.json, narration.json, subtitles.json, captions.ass, qa_report.json,
  publish.json, assets/, audio/, render/
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any, Callable, TypeVar

from pydantic import BaseModel

from .schemas import JobState, utcnow

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def atomic_write_json(path: Path, data: Any) -> None:
    if isinstance(data, BaseModel):
        text = data.model_dump_json(indent=2)
    else:
        text = json.dumps(data, ensure_ascii=False, indent=2, default=str)
    atomic_write_text(path, text)


def retry(fn: Callable[[], Any], attempts: int = 3, base_delay: float = 2.0,
          retry_on: tuple[type[BaseException], ...] = (Exception,), what: str = "") -> Any:
    """Cheklangan sonli qayta urinish (2s, 4s, 8s...). Oxirgi xato qayta ko'tariladi."""
    for i in range(1, attempts + 1):
        try:
            return fn()
        except retry_on as e:
            if i == attempts:
                raise
            delay = base_delay * 2 ** (i - 1)
            log.warning("%s: %d-urinish muvaffaqiyatsiz (%s). %.0fs dan keyin qayta.", what or fn, i, e, delay)
            time.sleep(delay)


class Job:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        for sub in ("assets", "audio", "render"):
            (self.root / sub).mkdir(exist_ok=True)
        self._meta_path = self.root / "job.json"
        self.meta: dict = json.loads(self._meta_path.read_text("utf-8")) if self._meta_path.exists() else {}
        self._handler: logging.Handler | None = None

    # ------------------------------------------------------------------ yaratish
    @classmethod
    def create(cls, jobs_dir: Path, category: str, extra: dict | None = None) -> "Job":
        job_id = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        job = cls(jobs_dir / job_id)
        job.meta = {"id": job_id, "category": category, "state": JobState.planned.value, "attempt": 1,
                    "created_at": utcnow(), "history": [], "errors": [], **(extra or {})}
        job.save()
        return job

    @classmethod
    def load(cls, jobs_dir: Path, job_id: str) -> "Job":
        root = jobs_dir / job_id
        if not (root / "job.json").exists():
            raise FileNotFoundError(f"ish topilmadi: {root}")
        return cls(root)

    @staticmethod
    def list_ids(jobs_dir: Path) -> list[str]:
        return sorted(p.parent.name for p in jobs_dir.glob("*/job.json")) if jobs_dir.exists() else []

    # --------------------------------------------------------------------- holat
    @property
    def id(self) -> str:
        return self.meta["id"]

    @property
    def state(self) -> JobState:
        return JobState(self.meta["state"])

    def save(self) -> None:
        atomic_write_json(self._meta_path, self.meta)

    def set_state(self, state: JobState, note: str = "") -> None:
        self.meta["state"] = state.value
        self.meta["history"].append({"at": utcnow(), "state": state.value, "note": note})
        self.save()
        log.info("[%s] holat -> %s %s", self.id, state.value, note)

    def record_error(self, stage: str, error: str) -> None:
        self.meta["errors"].append({"at": utcnow(), "stage": stage, "error": error[:2000]})
        self.save()

    # ---------------------------------------------------------------- artefaktlar
    def path(self, name: str) -> Path:
        return self.root / name

    def has(self, name: str) -> bool:
        return (self.root / name).exists()

    def write(self, name: str, data: Any) -> Path:
        p = self.root / name
        atomic_write_json(p, data)
        return p

    def read_json(self, name: str) -> Any:
        return json.loads((self.root / name).read_text("utf-8"))

    def read_model(self, name: str, model: type[T]) -> T:
        return model.model_validate_json((self.root / name).read_text("utf-8"))

    def invalidate(self, *names: str) -> None:
        """Keyingi bosqich qayta bajarilishi uchun artefaktlarni o'chiradi."""
        for n in names:
            p = self.root / n
            if p.exists():
                p.unlink()

    # ---------------------------------------------------------------------- log
    def attach_log(self) -> None:
        if self._handler is None:
            self._handler = logging.FileHandler(self.root / "job.log", encoding="utf-8")
            self._handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
            logging.getLogger("youtube_agent").addHandler(self._handler)

    def detach_log(self) -> None:
        if self._handler:
            logging.getLogger("youtube_agent").removeHandler(self._handler)
            self._handler.close()
            self._handler = None
