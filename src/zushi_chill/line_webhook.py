from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any


class WebhookError(ValueError):
    """Raised when a LINE webhook request cannot be trusted or parsed."""


@dataclass(frozen=True)
class MentionRequest:
    reply_token: str
    source_id: str
    source_type: str
    text: str


def verify_signature(body: bytes, signature: str, channel_secret: str) -> bool:
    if not channel_secret.strip() or not signature.strip():
        return False
    digest = hmac.new(channel_secret.strip().encode("utf-8"), body, hashlib.sha256).digest()
    expected_signature = base64.b64encode(digest).decode("ascii")
    return hmac.compare_digest(expected_signature, signature.strip())


def parse_mention_requests(body: bytes, *, bot_user_id: str = "") -> list[MentionRequest]:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WebhookError("LINE webhook body must be valid JSON") from exc

    events = payload.get("events")
    if not isinstance(events, list):
        raise WebhookError("LINE webhook body must contain events")

    mention_requests = []
    for event in events:
        if not isinstance(event, dict) or not _is_text_message_event(event):
            continue
        if not _mentions_bot(event, bot_user_id=bot_user_id):
            continue
        reply_token = event.get("replyToken", "")
        source = event.get("source") or {}
        if not isinstance(reply_token, str) or not isinstance(source, dict):
            continue
        source_id = _source_id(source)
        mention_requests.append(
            MentionRequest(
                reply_token=reply_token,
                source_id=source_id,
                source_type=str(source.get("type", "")),
                text=str(event["message"].get("text", "")),
            )
        )
    return mention_requests


def _is_text_message_event(event: dict[str, Any]) -> bool:
    message = event.get("message")
    return (
        event.get("type") == "message"
        and isinstance(message, dict)
        and message.get("type") == "text"
    )


def _mentions_bot(event: dict[str, Any], *, bot_user_id: str) -> bool:
    message = event.get("message") or {}
    if not isinstance(message, dict):
        return False
    mention = message.get("mention") or {}
    if not isinstance(mention, dict):
        return False
    mentionees = mention.get("mentionees")
    if not isinstance(mentionees, list):
        return False

    normalized_bot_user_id = bot_user_id.strip()
    for mentionee in mentionees:
        if not isinstance(mentionee, dict):
            continue
        if normalized_bot_user_id:
            if mentionee.get("userId") == normalized_bot_user_id:
                return True
        elif mentionee.get("type") == "user":
            return True
    return False


def _source_id(source: dict[str, Any]) -> str:
    for key in ("groupId", "roomId", "userId"):
        value = source.get(key)
        if isinstance(value, str) and value:
            return value
    return ""
