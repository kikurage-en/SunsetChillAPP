from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from zushi_chill import fireworks_batch
from zushi_chill.fireworks_batch import (
    AnalyzedCandidate,
    captured_at_from_path,
    parse_candidate_paths,
    process_candidate_batch,
    select_best_candidates,
)
from zushi_chill.fireworks_monitor import (
    FireworksAnalysis,
    FireworksMonitorError,
)

JST = ZoneInfo("Asia/Tokyo")


def _candidate(
    time_text: str,
    quality: int,
    confidence: int = 90,
) -> AnalyzedCandidate:
    captured_at = datetime.strptime(
        f"2026-07-30 {time_text}",
        "%Y-%m-%d %H%M%S",
    ).replace(tzinfo=JST)
    return AnalyzedCandidate(
        relative_path=(
            f"fireworks-candidates/2026-07-30/{time_text}-00001000.jpg"
        ),
        captured_at=captured_at,
        analysis=FireworksAnalysis(
            fireworks_visible=True,
            confidence=confidence,
            quality_score=quality,
            comment="花火を見つけたっピ！",
        ),
    )


def test_parse_candidate_paths_rejects_traversal_and_wrong_date():
    with pytest.raises(FireworksMonitorError, match="Invalid"):
        parse_candidate_paths('["../secret.jpg"]')
    with pytest.raises(FireworksMonitorError, match="Invalid"):
        parse_candidate_paths(
            '["fireworks-candidates/2026-07-29/194213-00001000.jpg"]'
        )


def test_captured_at_is_derived_from_validated_path():
    captured_at = captured_at_from_path(
        "fireworks-candidates/2026-07-30/194213-00001000.jpg",
        JST,
    )

    assert captured_at == datetime(2026, 7, 30, 19, 42, 13, tzinfo=JST)


def test_select_best_candidates_prioritizes_quality_and_separates_bursts():
    selected = select_best_candidates(
        [
            _candidate("194200", 70),
            _candidate("194210", 95),
            _candidate("194240", 80),
        ],
        max_images=2,
        minimum_interval_seconds=20,
    )

    assert [item.captured_at.strftime("%H%M%S") for item in selected] == [
        "194210",
        "194240",
    ]


def test_process_batch_filters_false_images_and_keeps_voiced_comments(
    monkeypatch,
    tmp_path,
):
    paths = [
        "fireworks-candidates/2026-07-30/194200-00001000.jpg",
        "fireworks-candidates/2026-07-30/194240-00002000.jpg",
    ]
    for path in paths:
        image = tmp_path / path
        image.parent.mkdir(parents=True, exist_ok=True)
        image.write_bytes(b"jpeg")
    analyses = iter(
        [
            FireworksAnalysis(False, 95, 90, ""),
            FireworksAnalysis(True, 96, 85, "大きな花火っピ！"),
        ]
    )
    monkeypatch.setattr(
        fireworks_batch,
        "analyze_fireworks_image",
        lambda **kwargs: next(analyses),
    )

    selected = process_candidate_batch(
        candidate_paths=paths,
        pages_dir=tmp_path,
        image_base_url="",
        api_key="key",
        vision_model="model",
        line_client=None,
        timezone=JST,
        dry_run=True,
    )

    assert len(selected) == 1
    assert selected[0].analysis.comment.endswith("っピ！")


def test_process_batch_reports_monitor_error_when_every_analysis_fails(
    monkeypatch,
    tmp_path,
):
    paths = [
        "fireworks-candidates/2026-07-30/194200-00001000.jpg",
        "fireworks-candidates/2026-07-30/194240-00002000.jpg",
    ]
    for path in paths:
        image = tmp_path / path
        image.parent.mkdir(parents=True, exist_ok=True)
        image.write_bytes(b"jpeg")

    def fail_analysis(**kwargs):
        raise FireworksMonitorError("Vision quota exhausted")

    class FakeLineClient:
        target_id = "target"

        def __init__(self):
            self.messages = []

        def push_text(self, text, *, retry_key=None):
            self.messages.append((text, retry_key))

    monkeypatch.setattr(
        fireworks_batch,
        "analyze_fireworks_image",
        fail_analysis,
    )
    line_client = FakeLineClient()

    selected = process_candidate_batch(
        candidate_paths=paths,
        pages_dir=tmp_path,
        image_base_url="https://example.test",
        api_key="key",
        vision_model="model",
        line_client=line_client,
        timezone=JST,
        dry_run=False,
    )

    assert selected == []
    assert len(line_client.messages) == 1
    assert "エラー" in line_client.messages[0][0]
    assert "確認できなかった" not in line_client.messages[0][0]


def test_process_batch_reports_monitor_error_when_partial_collection_has_no_match(
    monkeypatch,
    tmp_path,
):
    path = "fireworks-candidates/2026-07-30/194200-00001000.jpg"
    image = tmp_path / path
    image.parent.mkdir(parents=True, exist_ok=True)
    image.write_bytes(b"jpeg")

    class FakeLineClient:
        target_id = "target"

        def __init__(self):
            self.messages = []

        def push_text(self, text, *, retry_key=None):
            self.messages.append(text)

    monkeypatch.setattr(
        fireworks_batch,
        "analyze_fireworks_image",
        lambda **kwargs: FireworksAnalysis(False, 95, 0, ""),
    )
    line_client = FakeLineClient()

    selected = process_candidate_batch(
        candidate_paths=[path],
        pages_dir=tmp_path,
        image_base_url="https://example.test",
        api_key="key",
        vision_model="model",
        line_client=line_client,
        timezone=JST,
        dry_run=False,
        collection_incomplete=True,
    )

    assert selected == []
    assert len(line_client.messages) == 1
    assert "エラー" in line_client.messages[0]
    assert "確認できなかった" not in line_client.messages[0]
