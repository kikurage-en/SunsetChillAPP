from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from zoneinfo import ZoneInfo

from zushi_chill.fireworks_monitor import (
    DEFAULT_TIMEZONE,
    EVENT_DATE,
    MAX_IMAGES,
    MIN_SEND_INTERVAL_SECONDS,
    FireworksAnalysis,
    FireworksMonitorError,
    _notify_monitor_error,
    _notify_no_capture,
    _public_image_url,
    _send_candidate,
    analyze_fireworks_image,
    build_fireworks_comment,
)
from zushi_chill.line_client import LineClient

LOGGER = logging.getLogger(__name__)

_CANDIDATE_PATH = re.compile(
    rf"^fireworks-candidates/{EVENT_DATE}/(?P<time>\d{{6}})-\d{{8}}\.jpg$"
)


@dataclass(frozen=True)
class AnalyzedCandidate:
    relative_path: str
    captured_at: datetime
    analysis: FireworksAnalysis


def parse_candidate_paths(raw_json: str) -> list[str]:
    try:
        parsed = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise FireworksMonitorError("candidate_paths must be valid JSON") from exc
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        raise FireworksMonitorError("candidate_paths must be a JSON array of strings")
    if len(parsed) > 30:
        raise FireworksMonitorError("candidate_paths must contain at most 30 images")
    paths: list[str] = []
    for item in parsed:
        normalized = PurePosixPath(item).as_posix()
        if normalized != item or _CANDIDATE_PATH.fullmatch(item) is None:
            raise FireworksMonitorError(f"Invalid fireworks candidate path: {item}")
        paths.append(item)
    return paths


def captured_at_from_path(relative_path: str, timezone: ZoneInfo) -> datetime:
    match = _CANDIDATE_PATH.fullmatch(relative_path)
    if match is None:
        raise FireworksMonitorError(f"Invalid fireworks candidate path: {relative_path}")
    return datetime.strptime(
        f"{EVENT_DATE} {match.group('time')}",
        "%Y-%m-%d %H%M%S",
    ).replace(tzinfo=timezone)


def select_best_candidates(
    candidates: list[AnalyzedCandidate],
    *,
    max_images: int,
    minimum_interval_seconds: float = MIN_SEND_INTERVAL_SECONDS,
) -> list[AnalyzedCandidate]:
    ranked = sorted(
        candidates,
        key=lambda item: (
            -item.analysis.quality_score,
            -item.analysis.confidence,
            item.captured_at,
        ),
    )
    selected: list[AnalyzedCandidate] = []
    for candidate in ranked:
        if all(
            abs((candidate.captured_at - existing.captured_at).total_seconds())
            >= minimum_interval_seconds
            for existing in selected
        ):
            selected.append(candidate)
        if len(selected) >= max_images:
            break
    return sorted(selected, key=lambda item: item.captured_at)


def process_candidate_batch(
    *,
    candidate_paths: list[str],
    pages_dir: Path,
    image_base_url: str,
    api_key: str,
    vision_model: str,
    line_client: LineClient | None,
    timezone: ZoneInfo,
    dry_run: bool,
    max_images: int = MAX_IMAGES,
) -> list[AnalyzedCandidate]:
    analyzed: list[AnalyzedCandidate] = []
    for relative_path in candidate_paths:
        image_path = pages_dir / relative_path
        captured_at = captured_at_from_path(relative_path, timezone)
        try:
            analysis = analyze_fireworks_image(
                image_path=image_path,
                captured_at=captured_at,
                api_key=api_key,
                model=vision_model,
            )
        except FireworksMonitorError as exc:
            LOGGER.warning("Skipping unanalyzable candidate %s: %s", relative_path, exc)
            continue
        LOGGER.info(
            "Candidate %s: visible=%s confidence=%s quality=%s",
            relative_path,
            analysis.fireworks_visible,
            analysis.confidence,
            analysis.quality_score,
        )
        if (
            analysis.fireworks_visible
            and analysis.confidence >= 70
            and analysis.quality_score >= 35
        ):
            analyzed.append(
                AnalyzedCandidate(
                    relative_path=relative_path,
                    captured_at=captured_at,
                    analysis=analysis,
                )
            )

    selected = select_best_candidates(analyzed, max_images=max_images)
    if dry_run:
        for ordinal, candidate in enumerate(selected, start=1):
            LOGGER.info(
                "Dry-run selection %s: %s %s",
                ordinal,
                candidate.relative_path,
                candidate.analysis.comment,
            )
        return selected

    if line_client is None:
        raise FireworksMonitorError("LINE settings are required outside dry-run mode")
    if not selected:
        _notify_no_capture(line_client)
        return []
    for ordinal, candidate in enumerate(selected, start=1):
        comment = candidate.analysis.comment or build_fireworks_comment(
            candidate.captured_at,
            ordinal,
        )
        _send_candidate(
            line_client=line_client,
            target_id=line_client.target_id,
            captured_at=candidate.captured_at,
            comment=comment,
            image_url=_public_image_url(image_base_url, candidate.relative_path),
        )
    return selected


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze collected fireworks candidates and send the best images."
    )
    parser.add_argument("--candidate-paths-json", required=True)
    parser.add_argument("--status", choices=("ok", "monitor_error"), default="ok")
    parser.add_argument("--pages-dir", default="public")
    parser.add_argument("--max-images", type=int, default=MAX_IMAGES)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
        format="%(asctime)s %(levelname)s:%(name)s:%(message)s",
    )
    paths = parse_candidate_paths(args.candidate_paths_json)
    line_token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
    line_target = os.getenv("LINE_TARGET_ID", "")
    line_client = (
        None
        if args.dry_run
        else LineClient(channel_access_token=line_token, target_id=line_target)
    )
    if not args.dry_run and (not line_token.strip() or not line_target.strip()):
        raise FireworksMonitorError(
            "LINE_CHANNEL_ACCESS_TOKEN and LINE_TARGET_ID are required"
        )
    if args.status == "monitor_error":
        if line_client is not None:
            _notify_monitor_error(
                line_client,
                FireworksMonitorError("Local fireworks collection failed"),
            )
        else:
            LOGGER.warning("Dry-run monitor error notification")
        return 0

    api_key = os.getenv("VISION_API_KEY", "")
    if not api_key.strip():
        raise FireworksMonitorError("VISION_API_KEY is required")
    image_base_url = os.getenv("FIREWORKS_IMAGE_BASE_URL", "")
    if not args.dry_run and not image_base_url.strip():
        raise FireworksMonitorError("FIREWORKS_IMAGE_BASE_URL is required")
    process_candidate_batch(
        candidate_paths=paths,
        pages_dir=Path(args.pages_dir),
        image_base_url=image_base_url,
        api_key=api_key,
        vision_model=os.getenv("VISION_MODEL", "gemini-2.5-flash"),
        line_client=line_client,
        timezone=ZoneInfo(os.getenv("TIMEZONE", DEFAULT_TIMEZONE)),
        dry_run=args.dry_run,
        max_images=args.max_images,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
