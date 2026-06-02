from __future__ import annotations

import base64
import hashlib
import hmac
import json

import pytest
from zushi_chill.line_webhook import WebhookError, parse_mention_requests, verify_signature


def test_verify_signature_accepts_valid_line_signature():
    body = b'{"events":[]}'
    secret = "channel-secret"
    signature = base64.b64encode(
        hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    ).decode("ascii")

    assert verify_signature(body, signature, secret) is True
    assert verify_signature(body, "bad-signature", secret) is False


def test_parse_mention_requests_requires_configured_bot_user_id():
    body = json.dumps(
        {
            "events": [
                {
                    "type": "message",
                    "replyToken": "reply-token",
                    "source": {"type": "group", "groupId": "group-id"},
                    "message": {
                        "type": "text",
                        "text": "@bot いまの海は？",
                        "mention": {
                            "mentionees": [
                                {"type": "user", "userId": "bot-user-id", "index": 0, "length": 4}
                            ]
                        },
                    },
                }
            ]
        }
    ).encode("utf-8")

    assert parse_mention_requests(body, bot_user_id="other-user-id") == []
    requests = parse_mention_requests(body, bot_user_id="bot-user-id")

    assert len(requests) == 1
    assert requests[0].reply_token == "reply-token"
    assert requests[0].source_id == "group-id"
    assert requests[0].source_type == "group"
    assert requests[0].text == "@bot いまの海は？"


def test_parse_mention_requests_rejects_invalid_json():
    with pytest.raises(WebhookError, match="valid JSON"):
        parse_mention_requests(b"{not json")
