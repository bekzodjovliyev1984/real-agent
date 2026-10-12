"""Telegram Bot API bilan ishlash uchun yengil mijoz (long polling)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import httpx

from .net import http_client

log = logging.getLogger(__name__)

MAX_VIDEO_BYTES = 50 * 1024 * 1024  # Bot API orqali yuborish chegarasi


class TelegramBot:
    def __init__(self, token: str, chat_id: str):
        self.base = f"https://api.telegram.org/bot{token}"
        self.chat_id = chat_id
        self.offset = 0
        self.http = http_client(httpx.Timeout(60.0, read=70.0), headers={})

    def _call(self, method: str, **params) -> dict:
        files = params.pop("files", None)
        if "reply_markup" in params and not isinstance(params["reply_markup"], str):
            params["reply_markup"] = json.dumps(params["reply_markup"])
        if files:
            resp = self.http.post(f"{self.base}/{method}", data=params, files=files, timeout=300)
        else:
            resp = self.http.post(f"{self.base}/{method}", json=params)
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram {method} xatosi: {data}")
        return data["result"]

    @staticmethod
    def buttons(rows: list[list[tuple[str, str]]]) -> dict:
        return {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in row] for row in rows]}

    def send(self, text: str, buttons: dict | None = None, chat_id: str | None = None) -> dict:
        params = {"chat_id": chat_id or self.chat_id, "text": text[:4096], "disable_web_page_preview": True}
        if buttons:
            params["reply_markup"] = buttons
        return self._call("sendMessage", **params)

    def send_video(self, path: Path, caption: str, buttons: dict | None = None, thumb: Path | None = None) -> dict:
        """Videoni yuboradi; juda katta bo'lsa, faqat muqova rasmini yuboradi."""
        params = {"chat_id": self.chat_id, "caption": caption[:1024]}
        if buttons:
            params["reply_markup"] = json.dumps(buttons)
        if path.stat().st_size <= MAX_VIDEO_BYTES:
            with open(path, "rb") as f:
                return self._call("sendVideo", files={"video": f}, supports_streaming="true", **params)
        params["caption"] = (caption + "\n\n(Video 50MB dan katta, faqat muqova ko'rsatildi)")[:1024]
        with open(thumb, "rb") as f:
            return self._call("sendPhoto", files={"photo": f}, **params)

    def answer_callback(self, callback_id: str, text: str = "") -> None:
        try:
            self._call("answerCallbackQuery", callback_query_id=callback_id, text=text)
        except Exception as e:  # eskirgan callback - muhim emas
            log.debug("answerCallbackQuery: %s", e)

    def remove_buttons(self, message: dict, note: str) -> None:
        """Bosilgan xabardagi tugmalarni olib tashlab, natijani yozib qo'yadi."""
        try:
            self._call("editMessageReplyMarkup", chat_id=message["chat"]["id"],
                       message_id=message["message_id"], reply_markup={"inline_keyboard": []})
            self._call("sendMessage", chat_id=message["chat"]["id"], text=note,
                       reply_to_message_id=message["message_id"])
        except Exception as e:
            log.warning("Tugmalarni olib tashlab bo'lmadi: %s", e)

    def get_updates(self, timeout: int = 25) -> list[dict]:
        updates = self._call("getUpdates", offset=self.offset, timeout=timeout,
                             allowed_updates=["message", "callback_query"])
        if updates:
            self.offset = updates[-1]["update_id"] + 1
        return updates
