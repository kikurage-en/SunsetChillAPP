from __future__ import annotations

import json
import logging
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

LOGGER = logging.getLogger(__name__)

LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"


class LineSendError(RuntimeError):
    """Raised when LINE Messaging API push message fails."""


class LineClient:
    def __init__(self, *, channel_access_token: str, target_id: str, timeout: int = 20):
        self.channel_access_token = channel_access_token.strip()
        self.target_id = target_id.strip()
        self.timeout = timeout

    def push_text(self, text: str) -> None:
        self.push_messages([{"type": "text", "text": text}])

    def push_text_with_image(
        self, text: str, *, image_url: str, preview_image_url: str | None = None
    ) -> None:
        image_url = image_url.strip()
        preview_image_url = (preview_image_url or image_url).strip()
        if not image_url.startswith("https://") or not preview_image_url.startswith("https://"):
            raise LineSendError("LINE image URLs must start with https://")
        self.push_messages(
            [
                {"type": "text", "text": text},
                {
                    "type": "image",
                    "originalContentUrl": image_url,
                    "previewImageUrl": preview_image_url,
                },
            ]
        )

    def push_messages(self, messages: list[dict[str, str]]) -> None:
        if not self.channel_access_token:
            raise LineSendError("LINE channel access token is required")
        if not self.target_id:
            raise LineSendError("LINE target id is required")
        if not messages:
            raise LineSendError("LINE messages are required")
        payload = {
            "to": self.target_id,
            "messages": messages,
        }
        request = Request(
            LINE_PUSH_URL,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.channel_access_token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                if response.status >= 400:
                    body = response.read().decode("utf-8", errors="replace")
                    LOGGER.error("LINE push failed: HTTP %s %s", response.status, body)
                    raise LineSendError(f"LINE returned HTTP {response.status}: {body}")
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            LOGGER.error("LINE push failed: HTTP %s %s", exc.code, body)
            raise LineSendError(f"LINE returned HTTP {exc.code}: {body}") from exc
        except (URLError, TimeoutError) as exc:
            LOGGER.error("LINE push failed: %s", exc)
            raise LineSendError(f"LINE push failed: {exc}") from exc
