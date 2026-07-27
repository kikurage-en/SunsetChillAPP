from __future__ import annotations

import json
import logging
import uuid
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

LOGGER = logging.getLogger(__name__)

LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"
LINE_REPLY_URL = "https://api.line.me/v2/bot/message/reply"


class LineSendError(RuntimeError):
    """Raised when LINE Messaging API push message fails."""


class LineClient:
    def __init__(self, *, channel_access_token: str, target_id: str, timeout: int = 20):
        self.channel_access_token = channel_access_token.strip()
        self.target_id = target_id.strip()
        self.timeout = timeout

    def push_text(self, text: str, *, retry_key: str | None = None) -> None:
        self.push_messages([{"type": "text", "text": text}], retry_key=retry_key)

    def reply_text(self, reply_token: str, text: str) -> None:
        self.reply_messages(reply_token, [{"type": "text", "text": text}])

    def push_text_with_image(
        self,
        text: str,
        *,
        image_url: str,
        preview_image_url: str | None = None,
        retry_key: str | None = None,
    ) -> None:
        self.push_messages(
            [
                {"type": "text", "text": text},
                _image_message(image_url, preview_image_url),
            ],
            retry_key=retry_key,
        )

    def reply_image(
        self, reply_token: str, *, image_url: str, preview_image_url: str | None = None
    ) -> None:
        self.reply_messages(reply_token, [_image_message(image_url, preview_image_url)])

    def push_messages(
        self,
        messages: list[dict[str, str]],
        *,
        retry_key: str | None = None,
    ) -> None:
        if not self.channel_access_token:
            raise LineSendError("LINE channel access token is required")
        if not self.target_id:
            raise LineSendError("LINE target id is required")
        if not messages:
            raise LineSendError("LINE messages are required")
        payload = {"to": self.target_id, "messages": messages}
        self._post_json(LINE_PUSH_URL, payload, retry_key=retry_key)

    def reply_messages(self, reply_token: str, messages: list[dict[str, str]]) -> None:
        if not self.channel_access_token:
            raise LineSendError("LINE channel access token is required")
        if not reply_token.strip():
            raise LineSendError("LINE reply token is required")
        if not messages:
            raise LineSendError("LINE messages are required")
        payload = {"replyToken": reply_token.strip(), "messages": messages}
        self._post_json(LINE_REPLY_URL, payload)

    def _post_json(
        self,
        url: str,
        payload: dict,
        *,
        retry_key: str | None = None,
    ) -> None:
        headers = {
            "Authorization": f"Bearer {self.channel_access_token}",
            "Content-Type": "application/json",
        }
        if retry_key:
            _validate_retry_key(retry_key)
            headers["X-Line-Retry-Key"] = retry_key
        request = Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                if response.status == 409 and retry_key:
                    LOGGER.info("LINE retry key was already accepted; treating as sent")
                    return
                if response.status >= 400:
                    body = response.read().decode("utf-8", errors="replace")
                    LOGGER.error("LINE push failed: HTTP %s %s", response.status, body)
                    raise LineSendError(f"LINE returned HTTP {response.status}: {body}")
        except HTTPError as exc:
            if exc.code == 409 and retry_key:
                LOGGER.info("LINE retry key was already accepted; treating as sent")
                return
            body = exc.read().decode("utf-8", errors="replace")
            LOGGER.error("LINE push failed: HTTP %s %s", exc.code, body)
            raise LineSendError(f"LINE returned HTTP {exc.code}: {body}") from exc
        except (URLError, TimeoutError) as exc:
            LOGGER.error("LINE push failed: %s", exc)
            raise LineSendError(f"LINE push failed: {exc}") from exc


def observation_retry_key(*, observation_id: str, target_id: str) -> str:
    """Return a stable UUID for LINE retries of one scheduled observation."""
    if not observation_id.strip():
        raise ValueError("observation_id is required")
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"SunsetChillAPP:{target_id.strip()}:{observation_id.strip()}",
        )
    )


def _validate_retry_key(value: str) -> None:
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise LineSendError("LINE retry key must be a UUID") from exc
    if str(parsed) != value.lower():
        raise LineSendError("LINE retry key must use canonical UUID format")


def _image_message(image_url: str, preview_image_url: str | None = None) -> dict[str, str]:
    image_url = image_url.strip()
    preview_image_url = (preview_image_url or image_url).strip()
    if not image_url.startswith("https://") or not preview_image_url.startswith("https://"):
        raise LineSendError("LINE image URLs must start with https://")
    return {
        "type": "image",
        "originalContentUrl": image_url,
        "previewImageUrl": preview_image_url,
    }
