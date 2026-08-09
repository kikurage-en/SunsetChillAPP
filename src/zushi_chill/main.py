from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from zushi_chill.config import ConfigError, Settings
from zushi_chill.jma_client import JmaForecastClient
from zushi_chill.line_client import LineClient, observation_retry_key
from zushi_chill.live_camera import build_capture_relative_path, build_capture_url
from zushi_chill.message_builder import build_comment, build_line_message
from zushi_chill.models import (
    JmaPrecipitationForecast,
    PredictionRecord,
    ScoreResult,
    SunsetCloud,
    SunsethueResult,
    SunsetPredictionReference,
    VisionResult,
    WeatherSummary,
)
from zushi_chill.scoring import (
    blend_sunset_score,
    calculate_scores,
    has_rain_signal,
    score_label,
)
from zushi_chill.storage import Storage, storage_from_settings
from zushi_chill.sunset_geometry import sunset_cloud_point
from zushi_chill.sunsethue_client import fetch_sunset_quality
from zushi_chill.vision_client import analyze_image, vision_mode
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
        scheduled_at = _parse_observation_datetime(
            args.scheduled_at,
            tz,
            "--scheduled-at",
        )
        captured_at = _parse_observation_datetime(
            args.captured_at,
            tz,
            "--captured-at",
        )
        run_time = captured_at or _resolve_run_time(args.date, args.run_time, tz)
        _validate_observation_args(
            args,
            scheduled_at,
            captured_at,
            capture_window_minutes=args.capture_window_minutes,
        )
        dry_run = args.dry_run or settings.dry_run
        storage = storage_from_settings(settings)

        sent_query = {
            "date": run_time.date().isoformat(),
            "run_time": run_time.strftime("%H:%M"),
            "location_name": settings.location_name,
        }
        if args.observation_id:
            sent_query["observation_id"] = args.observation_id
        if not dry_run and storage.has_sent(**sent_query):
            logging.getLogger(__name__).info(
                "LINE already sent for %s %s %s (%s); skipping duplicate run",
                run_time.date().isoformat(),
                run_time.strftime("%H:%M"),
                settings.location_name,
                args.observation_id or "legacy run",
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
        sunset_cloud = _resolve_sunset_cloud(args, settings, summary, run_time)
        jma_precipitation = _collect_jma_precipitation(
            settings,
            summary,
            offline=bool(args.input_json),
        )
        mode = vision_mode(run_time, summary.sunset_time)
        scores_without_comment = calculate_scores(
            summary,
            sunset_cloud,
            chill_precipitation_probability=(
                jma_precipitation.probability if jma_precipitation else None
            ),
            chill_use_run_time_weather=mode == "actual",
        )
        live_camera_image_url = settings.live_camera_image_url or build_capture_url(
            settings.live_camera_image_base_url,
            build_capture_relative_path(run_time),
        )
        vision_result = _analyze_live_camera(
            settings, run_time, live_camera_image_url, summary.sunset_time
        )
        final_sunset_score, final_sunset_label = _blend_final_sunset(
            scores_without_comment, vision_result, mode, settings, summary
        )
        prior_sunset_prediction = _find_prior_sunset_prediction(
            storage,
            summary,
            mode=mode,
            vision=vision_result,
        )
        comment_scores = replace(
            scores_without_comment,
            sunset_score=final_sunset_score,
            sunset_label=final_sunset_label,
        )
        scores = replace(
            scores_without_comment,
            comment=build_comment(
                summary,
                comment_scores,
                sunset_cloud,
                prediction=mode == "predict",
                vision=vision_result,
                formula_sunset_score=scores_without_comment.sunset_score,
                jma_precipitation=jma_precipitation,
                prior_sunset_prediction=prior_sunset_prediction,
            ),
        )
        sunsethue_result = _collect_sunsethue(settings, run_time)
        message = build_line_message(
            summary,
            scores,
            vision=vision_result,
            vision_mode=mode,
            sunset_cloud=sunset_cloud,
            jma_precipitation=jma_precipitation,
            final_sunset_score=final_sunset_score,
            final_sunset_label=final_sunset_label,
            prior_sunset_prediction=prior_sunset_prediction,
        )

        if dry_run:
            record = PredictionRecord(
                summary=summary,
                scores=scores,
                line_sent=False,
                vision=vision_result,
                sunset_cloud=sunset_cloud,
                final_sunset_score=final_sunset_score,
                final_sunset_label=final_sunset_label,
                sunsethue=sunsethue_result,
                jma_precipitation=jma_precipitation,
                observation_id=args.observation_id,
                observation_phase=args.observation_phase,
                scheduled_at=scheduled_at,
                captured_at=captured_at,
            )
            _save_initial_record(storage, record)
            print(message)
            return 0

        pending_record = PredictionRecord(
            summary=summary,
            scores=scores,
            line_sent=False,
            vision=vision_result,
            sunset_cloud=sunset_cloud,
            final_sunset_score=final_sunset_score,
            final_sunset_label=final_sunset_label,
            sunsethue=sunsethue_result,
            jma_precipitation=jma_precipitation,
            observation_id=args.observation_id,
            observation_phase=args.observation_phase,
            scheduled_at=scheduled_at,
            captured_at=captured_at,
        )
        _save_initial_record(storage, pending_record)
        try:
            settings.require_line()
            line_client = LineClient(
                channel_access_token=settings.line_channel_access_token,
                target_id=settings.line_target_id,
            )
            line_retry_key = (
                observation_retry_key(
                    observation_id=args.observation_id,
                    target_id=settings.line_target_id,
                )
                if args.observation_id
                else None
            )
            if live_camera_image_url:
                line_client.push_text_with_image(
                    message,
                    image_url=live_camera_image_url,
                    preview_image_url=settings.live_camera_preview_image_url
                    or live_camera_image_url,
                    **({"retry_key": line_retry_key} if line_retry_key else {}),
                )
            else:
                line_client.push_text(
                    message,
                    **({"retry_key": line_retry_key} if line_retry_key else {}),
                )
        except Exception as exc:
            failed_record = PredictionRecord(
                summary=summary,
                scores=scores,
                line_sent=False,
                error_message=str(exc),
                vision=vision_result,
                sunset_cloud=sunset_cloud,
                final_sunset_score=final_sunset_score,
                final_sunset_label=final_sunset_label,
                sunsethue=sunsethue_result,
                jma_precipitation=jma_precipitation,
                observation_id=args.observation_id,
                observation_phase=args.observation_phase,
                scheduled_at=scheduled_at,
                captured_at=captured_at,
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
            summary=summary,
            scores=scores,
            line_sent=True,
            vision=vision_result,
            sunset_cloud=sunset_cloud,
            final_sunset_score=final_sunset_score,
            final_sunset_label=final_sunset_label,
            sunsethue=sunsethue_result,
            jma_precipitation=jma_precipitation,
            observation_id=args.observation_id,
            observation_phase=args.observation_phase,
            scheduled_at=scheduled_at,
            captured_at=captured_at,
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


def _find_prior_sunset_prediction(
    storage: Storage,
    summary: WeatherSummary,
    *,
    mode: str,
    vision: VisionResult | None,
) -> SunsetPredictionReference | None:
    """同日に送信済みの日没前予測を、夕方に近い順で取得する。"""
    if mode != "actual" or vision is None:
        return None
    sunset_clock = summary.sunset_time.strftime("%H:%M")
    try:
        for prediction_time in ("17:00", "13:00"):
            if prediction_time >= sunset_clock:
                continue
            prediction = storage.find_sent_sunset_prediction(
                date=summary.date,
                run_time=prediction_time,
                location_name=summary.location_name,
            )
            if prediction is not None:
                return prediction
    except Exception as exc:
        logging.getLogger(__name__).warning(
            "Prior sunset prediction lookup failed; using current weather comparison: %s",
            exc,
        )
    return None


def _collect_sunsethue(settings: Settings, run_time: datetime) -> SunsethueResult | None:
    """Sunsethue(ray-model)の夕焼け品質予測を log-only で取得する。

    スコアには影響させず、式・Vision と突合するためのベンチマークとして記録するだけ。
    無効・キー未設定なら None。取得失敗は非致命(警告して継続)。座標は逗子海岸を渡す
    (ray-model が西の光路を内部評価するため西地点分離は不要)。
    """
    if not (settings.sunsethue_enabled and settings.sunsethue_api_key):
        return None
    try:
        return fetch_sunset_quality(
            latitude=settings.latitude,
            longitude=settings.longitude,
            target_date=run_time.date(),
            api_key=settings.sunsethue_api_key,
            timeout=settings.sunsethue_timeout_seconds,
        )
    except Exception as exc:
        logging.getLogger(__name__).warning("Sunsethue fetch failed; continuing: %s", exc)
        return None


def _collect_jma_precipitation(
    settings: Settings,
    summary: WeatherSummary,
    *,
    offline: bool,
) -> JmaPrecipitationForecast | None:
    """Fetch JMA's public six-hour PoP for LINE display and Chill scoring.

    The request is non-fatal: replay runs and temporary JMA failures retain the existing
    Open-Meteo value, while successful values are persisted for forward validation.
    """
    if offline or not settings.jma_forecast_enabled:
        return None
    try:
        return JmaForecastClient(
            timeout=settings.jma_timeout_seconds
        ).fetch_precipitation_probability(
            office_code=settings.jma_office_code,
            area_code=settings.jma_area_code,
            target_time=summary.sunset_time,
        )
    except Exception as exc:
        logging.getLogger(__name__).warning(
            "JMA precipitation forecast fetch failed; using Open-Meteo fallback: %s",
            exc,
        )
        return None


def _blend_final_sunset(
    scores: ScoreResult,
    vision: VisionResult | None,
    mode: str,
    settings: Settings,
    summary: WeatherSummary,
) -> tuple[int, str]:
    """表示用 Sunset期待度(式とVisionカメラAI予測のブレンド)とラベルを返す。

    ブレンドするのは日没前(予測モード)でVision解析が成功した実行のみ。日没時・
    残照の画像評価、Vision欠測、重み0ではブレンドせず純式スコアを返す。
    純式スコア ``scores.sunset_score`` はここでは変えない(呼び出し側でログ保持)。
    雨シグナル時はVisionによる上方修正を無効化する(下方修正は維持)。カメラは
    「これから来る雨」を見えない(2026-07-25: 窓内4.7mm・コード61の予報下でVision65が
    表示を45→61へ持ち上げ、実際の日没時発色は0だった)。
    """
    if vision is not None and mode == "predict" and settings.sunset_vision_blend_weight > 0:
        blended = blend_sunset_score(
            scores.sunset_score,
            vision.sunset_score,
            settings.sunset_vision_blend_weight,
        )
        if has_rain_signal(summary):
            blended = min(blended, scores.sunset_score)
        return blended, score_label(blended)
    return scores.sunset_score, scores.sunset_label


def _fetch_west_summary(
    args: argparse.Namespace,
    settings: Settings,
    run_time: datetime,
    offset_km: float,
) -> WeatherSummary:
    latitude, longitude = sunset_cloud_point(
        settings.latitude,
        settings.longitude,
        run_time.date(),
        offset_km,
    )
    payload = OpenMeteoClient().fetch_forecast(
        latitude=latitude,
        longitude=longitude,
        timezone=settings.timezone,
        target_date=run_time.date() if args.date else None,
    )
    return parse_forecast(
        payload,
        location_name=settings.location_name,
        latitude=latitude,
        longitude=longitude,
        timezone=settings.timezone,
        run_time=run_time,
        allow_missing_fields=settings.allow_missing_hourly_fields,
    )


def _resolve_sunset_cloud(
    args: argparse.Namespace,
    settings: Settings,
    summary: WeatherSummary,
    run_time: datetime,
) -> SunsetCloud:
    """Sunset期待度に使う雲量を、日没方位の地点から層別に取得する。

    遮蔽側の低層雲と総雲量は ``SUNSET_CLOUD_OFFSET_KM``(既定40km)の地点、発色源の
    中・高層雲(日没後も日照が届く、観測者寄りの「キャンバス」)は
    ``SUNSET_CLOUD_NEAR_OFFSET_KM``(既定20km)の地点から取る。
    ``SUNSET_CLOUD_OFFSET_KM<=0`` または ``--input-json``(オフライン再現)では
    逗子の雲量を使う。取得に失敗しても実行は止めない(far失敗=逗子へ、
    near失敗=far地点の値へフォールバック)。
    """
    if settings.sunset_cloud_offset_km <= 0 or args.input_json:
        return SunsetCloud.from_summary(summary)
    try:
        far = _fetch_west_summary(args, settings, run_time, settings.sunset_cloud_offset_km)
    except Exception as exc:
        logging.getLogger(__name__).warning(
            "Western sunset-cloud fetch failed; falling back to Zushi clouds: %s", exc
        )
        return SunsetCloud.from_summary(summary)

    near_km = settings.sunset_cloud_near_offset_km
    if near_km == settings.sunset_cloud_offset_km:
        near: WeatherSummary = far
    elif near_km <= 0:
        near = summary
    else:
        try:
            near = _fetch_west_summary(args, settings, run_time, near_km)
        except Exception as exc:
            logging.getLogger(__name__).warning(
                "Near sunset-cloud fetch failed; using far-point mid/high clouds: %s", exc
            )
            near = far
    return SunsetCloud(
        cloud_cover=far.cloud_cover,
        cloud_cover_low=far.cloud_cover_low,
        cloud_cover_mid=near.cloud_cover_mid,
        cloud_cover_high=near.cloud_cover_high,
        cloud_cover_low_at_sunset=far.cloud_cover_low_at_sunset,
        cloud_cover_mid_at_sunset=near.cloud_cover_mid_at_sunset,
        cloud_cover_high_at_sunset=near.cloud_cover_high_at_sunset,
    )


def _should_run_vision(run_time: datetime, settings: Settings) -> bool:
    return bool(
        settings.vision_enabled
        and settings.vision_api_key
        and run_time.hour in settings.vision_target_hours
    )


def _analyze_live_camera(
    settings: Settings, run_time: datetime, image_url: str, sunset_time: datetime
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
            capture_time=run_time,
            sunset_time=sunset_time,
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
        "--observation-id",
        default="",
        help="Stable idempotency key such as YYYY-MM-DD:sunset.",
    )
    parser.add_argument(
        "--observation-phase",
        choices=["sunset", "afterglow"],
        default="",
        help="Logical observation phase.",
    )
    parser.add_argument(
        "--scheduled-at",
        default="",
        help="Planned observation timestamp as a timezone-aware ISO-8601 value.",
    )
    parser.add_argument(
        "--captured-at",
        default="",
        help="Actual image capture timestamp as a timezone-aware ISO-8601 value.",
    )
    parser.add_argument(
        "--capture-window-minutes",
        type=int,
        default=10,
        help="How many minutes before scheduled_at an afterglow capture may occur.",
    )
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


def _parse_observation_datetime(
    value: str,
    tz: ZoneInfo,
    option_name: str,
) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ConfigError(f"{option_name} must be an ISO-8601 datetime") from exc
    if parsed.tzinfo is None:
        raise ConfigError(f"{option_name} must include a timezone offset")
    return parsed.astimezone(tz)


def _validate_observation_args(
    args: argparse.Namespace,
    scheduled_at: datetime | None,
    captured_at: datetime | None,
    *,
    capture_window_minutes: int = 10,
) -> None:
    values = (
        args.observation_id,
        args.observation_phase,
        scheduled_at,
        captured_at,
    )
    if any(values) and not all(values):
        raise ConfigError(
            "--observation-id, --observation-phase, --scheduled-at, and --captured-at "
            "must be provided together"
        )
    if capture_window_minutes < 0:
        raise ConfigError("--capture-window-minutes cannot be negative")
    if (
        args.observation_phase == "afterglow"
        and scheduled_at
        and captured_at
        and captured_at < scheduled_at - timedelta(minutes=capture_window_minutes)
    ):
        raise ConfigError(
            "--captured-at cannot be more than "
            f"{capture_window_minutes} minutes before --scheduled-at"
        )
    if args.observation_id and args.observation_id != (
        f"{scheduled_at.date().isoformat()}:{args.observation_phase}"
    ):
        raise ConfigError("--observation-id must match scheduled date and observation phase")


def _save_initial_record(storage, record: PredictionRecord) -> None:
    if record.observation_id:
        storage.replace_latest(record)
    else:
        storage.save(record)


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
