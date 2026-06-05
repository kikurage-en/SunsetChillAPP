from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from zushi_chill.config import ConfigError, Settings
from zushi_chill.line_client import LineClient
from zushi_chill.live_camera import build_capture_relative_path, build_capture_url
from zushi_chill.message_builder import build_comment, build_line_message
from zushi_chill.models import PredictionRecord, VisionResult
from zushi_chill.scoring import calculate_scores
from zushi_chill.storage import storage_from_settings
from zushi_chill.vision_client import analyze_image
from zushi_chill.weather_client import OpenMeteoClient, parse_forecast


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        settings = Settings.from_env()
        logging.basicConfig(
            level=getattr(logging, settings.log_level.upper(), logging.INFO),
            format="%(levelname)s:%(name)s:%(message)s",
        )
        tz = ZoneInfo(settings.timezone)
        run_time = _resolve_run_time(args.date, args.run_time, tz)
        dry_run = args.dry_run or settings.dry_run
        storage = storage_from_settings(settings)

        if not dry_run and storage.has_sent(
            date=run_time.date().isoformat(),
            run_time=run_time.strftime("%H:%M"),
            location_name=settings.location_name,
        ):
            logging.getLogger(__name__).info(
                "LINE already sent for %s %s %s; skipping duplicate run",
                run_time.date().isoformat(),
                run_time.strftime("%H:%M"),
                settings.location_name,
            )
            return 0

        payload = _load_payload(args, settings, run_time)
        summary = parse_forecast(
            payload,
            location_name=settings.location_name,
            latitude=settings.latitude,
            longitude=settings.longitude,
            timezone=settings.timezone,
            run_time=run_time,
            allow_missing_fields=settings.allow_missing_hourly_fields,
        )
        scores_without_comment = calculate_scores(summary)
        scores = replace(
            scores_without_comment,
            comment=build_comment(summary, scores_without_comment),
        )
        live_camera_image_url = settings.live_camera_image_url or build_capture_url(
            settings.live_camera_image_base_url,
            build_capture_relative_path(run_time),
        )
        vision_result = _analyze_live_camera(settings, run_time, live_camera_image_url)
        message = build_line_message(
            summary,
            scores,
            vision=vision_result,
            google_form_url=settings.google_form_url,
        )

        if dry_run:
            record = PredictionRecord(
                summary=summary, scores=scores, line_sent=False, vision=vision_result
            )
            storage.save(record)
            print(message)
            return 0

        pending_record = PredictionRecord(
            summary=summary, scores=scores, line_sent=False, vision=vision_result
        )
        storage.save(pending_record)
        try:
            settings.require_line()
            line_client = LineClient(
                channel_access_token=settings.line_channel_access_token,
                target_id=settings.line_target_id,
            )
            if live_camera_image_url:
                line_client.push_text_with_image(
                    message,
                    image_url=live_camera_image_url,
                    preview_image_url=settings.live_camera_preview_image_url
                    or live_camera_image_url,
                )
            else:
                line_client.push_text(message)
        except Exception as exc:
            failed_record = PredictionRecord(
                summary=summary,
                scores=scores,
                line_sent=False,
                error_message=str(exc),
                vision=vision_result,
            )
            try:
                storage.replace_latest(failed_record)
            except Exception:
                logging.getLogger(__name__).exception(
                    "LINE failed and failed to update storage with the error"
                )
                raise
            raise

        sent_record = PredictionRecord(
            summary=summary, scores=scores, line_sent=True, vision=vision_result
        )
        try:
            storage.replace_latest(sent_record)
        except Exception:
            logging.getLogger(__name__).exception("LINE sent but failed to update storage")
            raise
        return 0
    except Exception as exc:
        logging.getLogger(__name__).exception("Run failed: %s", exc)
        return 1


def _should_run_vision(run_time: datetime, settings: Settings) -> bool:
    return bool(
        settings.vision_enabled
        and settings.vision_api_key
        and run_time.hour == settings.vision_target_hour
    )


def _analyze_live_camera(
    settings: Settings, run_time: datetime, image_url: str
) -> VisionResult | None:
    if not _should_run_vision(run_time, settings):
        return None
    local_image_path = Path(settings.live_camera_public_dir) / build_capture_relative_path(run_time)
    try:
        return analyze_image(
            image_path=local_image_path if local_image_path.exists() else None,
            image_url=image_url,
            api_key=settings.vision_api_key,
            model=settings.vision_model,
            timeout_seconds=settings.vision_timeout_seconds,
        )
    except Exception as exc:
        logging.getLogger(__name__).warning("Vision analysis failed; continuing: %s", exc)
        return None


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Zushi sunset chill index MVP.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print message without sending LINE.",
    )
    parser.add_argument("--date", help="Run date in YYYY-MM-DD. Used for log display run_time.")
    parser.add_argument("--run-time", help="Run time in HH:MM, Asia/Tokyo by default.")
    parser.add_argument(
        "--input-json",
        help="Read an Open-Meteo response JSON file instead of calling the API.",
    )
    return parser.parse_args(argv)


def _load_payload(args: argparse.Namespace, settings: Settings, run_time: datetime) -> dict:
    if args.input_json:
        input_path = Path(args.input_json)
        try:
            with input_path.open(encoding="utf-8") as file:
                return json.load(file)
        except FileNotFoundError as exc:
            raise ConfigError(f"--input-json file not found: {input_path}") from exc
        except json.JSONDecodeError as exc:
            raise ConfigError(f"--input-json contains invalid JSON: {input_path}") from exc

    weather_client = OpenMeteoClient()
    return weather_client.fetch_forecast(
        latitude=settings.latitude,
        longitude=settings.longitude,
        timezone=settings.timezone,
        target_date=run_time.date() if args.date else None,
    )


def _resolve_run_time(date_value: str | None, run_time_value: str | None, tz: ZoneInfo) -> datetime:
    now = datetime.now(tz)
    if not date_value and not run_time_value:
        return now

    date_part = date_value or now.date().isoformat()
    time_part = run_time_value or now.strftime("%H:%M")
    if not _is_date_value(date_part) or not _is_time_value(time_part):
        raise ConfigError("--date must be YYYY-MM-DD and --run-time must be HH:MM")
    try:
        return datetime.fromisoformat(f"{date_part}T{time_part}").replace(tzinfo=tz)
    except ValueError as exc:
        raise ConfigError("--date must be YYYY-MM-DD and --run-time must be HH:MM") from exc


def _is_date_value(value: str) -> bool:
    return (
        len(value) == 10
        and value[4] == "-"
        and value[7] == "-"
        and value[:4].isdigit()
        and value[5:7].isdigit()
        and value[8:10].isdigit()
    )


def _is_time_value(value: str) -> bool:
    return len(value) == 5 and value[2] == ":" and value[:2].isdigit() and value[3:5].isdigit()


if __name__ == "__main__":
    sys.exit(main())
