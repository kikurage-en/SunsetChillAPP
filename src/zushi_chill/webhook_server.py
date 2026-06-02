from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

from zushi_chill.config import Settings
from zushi_chill.line_client import LineClient
from zushi_chill.line_webhook import WebhookError, parse_mention_requests, verify_signature
from zushi_chill.live_camera import (
    LiveCameraError,
    build_capture_url,
    capture_live_camera_image,
)

LOGGER = logging.getLogger(__name__)
WEBHOOK_PATH = "/line/webhook"


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    settings = Settings.from_env()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(levelname)s:%(name)s:%(message)s",
    )
    settings.require_webhook()
    host = args.host or settings.webhook_host
    port = args.port or settings.webhook_port
    server = ThreadingHTTPServer((host, port), _handler_class(settings))
    LOGGER.info("Starting LINE webhook server on %s:%s", host, port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        LOGGER.info("Stopping LINE webhook server")
    finally:
        server.server_close()
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Zushi Chill LINE webhook server.")
    parser.add_argument("--host", help="Host to bind. Defaults to WEBHOOK_HOST.")
    parser.add_argument("--port", type=int, help="Port to bind. Defaults to WEBHOOK_PORT.")
    return parser.parse_args(argv)


def _handler_class(settings: Settings):
    class LineWebhookHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/healthz":
                self._write_response(200, b"ok")
                return
            self._write_response(404, b"not found")

        def do_POST(self) -> None:
            if self.path != WEBHOOK_PATH:
                self._write_response(404, b"not found")
                return

            content_length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(content_length)
            signature = self.headers.get("X-Line-Signature", "")
            if not verify_signature(body, signature, settings.line_channel_secret):
                self._write_response(403, b"invalid signature")
                return

            try:
                mention_requests = parse_mention_requests(
                    body,
                    bot_user_id=settings.line_bot_user_id,
                )
            except WebhookError as exc:
                LOGGER.warning("Invalid LINE webhook body: %s", exc)
                self._write_response(400, b"invalid body")
                return

            line_client = LineClient(
                channel_access_token=settings.line_channel_access_token,
                target_id=settings.line_target_id,
            )
            for mention_request in mention_requests:
                self._reply_live_camera(line_client, mention_request.reply_token)

            self._write_response(200, b"ok")

        def log_message(self, format: str, *args) -> None:
            LOGGER.info("%s - %s", self.address_string(), format % args)

        def _reply_live_camera(self, line_client: LineClient, reply_token: str) -> None:
            now = datetime.now(ZoneInfo(settings.timezone))
            relative_path = (
                f"live-camera/mentions/{now.date().isoformat()}/{now.strftime('%H%M%S')}.jpg"
            )
            image_path = Path(settings.live_camera_public_dir) / relative_path
            try:
                capture_live_camera_image(
                    live_camera_url=settings.live_camera_url,
                    live_camera_video_id=settings.live_camera_video_id,
                    output_path=image_path,
                    timeout_seconds=settings.live_camera_capture_timeout_seconds,
                )
                image_url = build_capture_url(settings.live_camera_image_base_url, relative_path)
                line_client.reply_image(reply_token, image_url=image_url)
            except LiveCameraError as exc:
                LOGGER.warning("Mention capture failed: %s", exc)
                line_client.reply_text(reply_token, "ライブカメラ画像を取得できませんでした。")

        def _write_response(self, status: int, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return LineWebhookHandler


if __name__ == "__main__":
    sys.exit(main())
