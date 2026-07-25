from __future__ import annotations

import hashlib
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from zushi_chill import main as chill_main
from zushi_chill.config import Settings
from zushi_chill.live_camera import (
    LiveCameraError,
    build_capture_relative_path,
    build_capture_url,
    capture_live_camera_image,
)

LOGGER = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    args = chill_main._parse_args(argv)
    settings = Settings.from_env()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(levelname)s:%(name)s:%(message)s",
    )
    run_time = chill_main._resolve_run_time(args.date, args.run_time, ZoneInfo(settings.timezone))
    relative_path = build_capture_relative_path(run_time)

    if settings.live_camera_image_base_url and (
        settings.live_camera_url or settings.live_camera_video_id
    ):
        try:
            image_path = Path(settings.live_camera_public_dir) / relative_path
            capture_source = capture_live_camera_image(
                live_camera_url=settings.live_camera_url,
                live_camera_video_id=settings.live_camera_video_id,
                output_path=image_path,
                timeout_seconds=settings.live_camera_capture_timeout_seconds,
            )
            os.environ["LIVE_CAMERA_IMAGE_URL"] = build_capture_url(
                settings.live_camera_image_base_url,
                relative_path,
            )
            os.environ["LIVE_CAMERA_CAPTURE_SOURCE"] = capture_source
            os.environ["LIVE_CAMERA_CAPTURED_AT"] = datetime.now(
                ZoneInfo(settings.timezone)
            ).isoformat(timespec="seconds")
            os.environ["LIVE_CAMERA_IMAGE_SHA256"] = hashlib.sha256(
                image_path.read_bytes()
            ).hexdigest()
            LOGGER.info("Live camera image URL: %s", os.environ["LIVE_CAMERA_IMAGE_URL"])
        except LiveCameraError as exc:
            LOGGER.warning("Live camera image capture failed; sending text only: %s", exc)
    else:
        LOGGER.info("Live camera capture is not configured; sending text only")

    return chill_main.main(argv)


if __name__ == "__main__":
    sys.exit(main())
