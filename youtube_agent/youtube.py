"""YouTube Data API v3: video yuklash, kommentlarni o'qish va javob yozish."""

from __future__ import annotations

import logging
import random
import time
from datetime import datetime, timezone
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

log = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",  # kommentlar uchun
    "https://www.googleapis.com/auth/yt-analytics.readonly",  # statistika uchun
]
RETRIABLE_STATUS = {500, 502, 503, 504}
PRIVACY = {"private", "unlisted", "public", "scheduled"}


def authorize(client_secret: str, token_file: str) -> None:
    """Bir martalik: brauzerda Google akkauntga kirib, token.json yaratadi."""
    flow = InstalledAppFlow.from_client_secrets_file(client_secret, SCOPES)
    creds = flow.run_local_server(port=0, open_browser=True)
    Path(token_file).write_text(creds.to_json(), encoding="utf-8")
    print(f"Tayyor! Token saqlandi: {token_file}")


class YouTube:
    def __init__(self, token_file: str):
        if not Path(token_file).exists():
            raise RuntimeError(f"{token_file} topilmadi. Avval: python -m youtube_agent auth")
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)
        if not creds.valid and creds.refresh_token:
            creds.refresh(Request())
            Path(token_file).write_text(creds.to_json(), encoding="utf-8")
        self.creds = creds
        self.api = build("youtube", "v3", credentials=creds, cache_discovery=False)
        self._channel_id: str | None = None
        self._titles: dict[str, str] = {}

    @property
    def channel_id(self) -> str:
        if not self._channel_id:
            items = self.api.channels().list(part="id,snippet", mine=True).execute().get("items", [])
            if not items:
                raise RuntimeError("Bu Google akkauntda YouTube kanal yo'q. youtube.com da kanal yarating.")
            self._channel_id = items[0]["id"]
        return self._channel_id

    def upload(self, video: Path, thumb: Path | None, title: str, description: str, tags: list[str],
               category_id: str, publish_at: datetime | None = None, privacy: str = "private") -> str:
        """Videoni yuklaydi.
        privacy: private (sinov uchun standart) | unlisted | public | scheduled (publish_at vaqtida o'zi ochiladi)."""
        if privacy not in PRIVACY:
            raise ValueError(f"noto'g'ri privacy: {privacy}")
        status = {"selfDeclaredMadeForKids": False, "containsSyntheticMedia": True}
        if privacy == "scheduled":
            if publish_at and publish_at > datetime.now(timezone.utc):
                status["privacyStatus"] = "private"
                status["publishAt"] = publish_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
            else:
                status["privacyStatus"] = "public"
        else:
            status["privacyStatus"] = privacy
        body = {
            "snippet": {"title": title, "description": description, "tags": tags[:30], "categoryId": category_id},
            "status": status,
        }
        media = MediaFileUpload(str(video), mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True)
        req = self.api.videos().insert(part="snippet,status", body=body, media_body=media)
        response, errors = None, 0
        while response is None:
            try:
                prog, response = req.next_chunk()
                if prog:
                    log.info("Yuklanmoqda: %d%%", int(prog.progress() * 100))
            except HttpError as e:
                if e.resp.status not in RETRIABLE_STATUS:
                    raise
                errors += 1
            except (ConnectionError, TimeoutError, OSError):
                errors += 1
            else:
                continue
            if errors > 5:
                raise RuntimeError("YouTube'ga yuklash 5 marta uzildi, keyinroq qayta urinib ko'ring")
            delay = min(60, 2 ** errors + random.random())
            log.warning("Yuklash uzildi, %.0fs dan keyin davom etadi (%d/5)", delay, errors)
            time.sleep(delay)
        video_id = response["id"]
        if thumb:
            try:
                self.api.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(str(thumb))).execute()
            except HttpError as e:  # tasdiqlanmagan kanallarda muqova qo'yib bo'lmaydi
                log.warning("Muqova qo'yilmadi (kanalni telefon orqali tasdiqlang): %s", e)
        return video_id

    def video_status(self, video_id: str) -> dict:
        """Yuklangan videoning haqiqiy holati (YouTube qayta ishlashi, maxfiylik, davomiylik)."""
        items = self.api.videos().list(part="status,contentDetails,snippet", id=video_id).execute().get("items", [])
        if not items:
            return {"found": False}
        it = items[0]
        return {"found": True, "uploadStatus": it["status"].get("uploadStatus"),
                "privacyStatus": it["status"].get("privacyStatus"), "publishAt": it["status"].get("publishAt"),
                "duration": it["contentDetails"].get("duration"), "title": it["snippet"].get("title")}

    def video_title(self, video_id: str) -> str:
        if video_id not in self._titles:
            items = self.api.videos().list(part="snippet", id=video_id).execute().get("items", [])
            self._titles[video_id] = items[0]["snippet"]["title"] if items else video_id
        return self._titles[video_id]

    def recent_comments(self, since: datetime) -> list[dict]:
        """Kanaldagi yangi top-level kommentlar (kanal egasining o'zinikidan tashqari)."""
        resp = self.api.commentThreads().list(
            part="snippet", allThreadsRelatedToChannelId=self.channel_id,
            order="time", maxResults=50, textFormat="plainText",
        ).execute()
        result = []
        for item in resp.get("items", []):
            top = item["snippet"]["topLevelComment"]["snippet"]
            published = datetime.fromisoformat(top["publishedAt"].replace("Z", "+00:00"))
            if published < since:
                continue
            if top.get("authorChannelId", {}).get("value") == self.channel_id:
                continue
            if item["snippet"].get("totalReplyCount", 0) and self._channel_replied(item["id"]):
                continue
            result.append({
                "thread_id": item["id"],
                "video_id": top.get("videoId", ""),
                "author": top.get("authorDisplayName", ""),
                "text": top.get("textDisplay", ""),
            })
        return result

    def _channel_replied(self, thread_id: str) -> bool:
        replies = self.api.comments().list(part="snippet", parentId=thread_id, maxResults=50).execute()
        return any(r["snippet"].get("authorChannelId", {}).get("value") == self.channel_id
                   for r in replies.get("items", []))

    def reply(self, thread_id: str, text: str) -> None:
        self.api.comments().insert(
            part="snippet", body={"snippet": {"parentId": thread_id, "textOriginal": text}}
        ).execute()
