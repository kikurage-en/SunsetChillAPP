from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from zushi_chill import afterglow_selector
from zushi_chill.live_camera import LiveCameraFrame

JST = ZoneInfo("Asia/Tokyo")


def test_sunset_color_score_prefers_vivid_orange_to_gray_and_dark():
    orange = bytes([230, 80, 20]) * 100
    gray = bytes([120, 120, 120]) * 100
    dark_red = bytes([15, 2, 2]) * 100

    assert afterglow_selector._sunset_color_score(orange) > 80
    assert afterglow_selector._sunset_color_score(gray) == 0
    assert afterglow_selector._sunset_color_score(dark_red) < 30


def test_rank_afterglow_candidates_deduplicates_and_sorts_by_local_score(
    tmp_path,
    monkeypatch,
):
    started_at = datetime(2026, 7, 26, 19, 5, tzinfo=JST)
    orange = tmp_path / "frame-001.jpg"
    gray = tmp_path / "frame-002.jpg"
    duplicate_orange = tmp_path / "frame-003.jpg"
    orange.write_bytes(b"orange-jpeg")
    gray.write_bytes(b"gray-jpeg")
    duplicate_orange.write_bytes(b"orange-jpeg")
    frames = (
        LiveCameraFrame(orange, started_at),
        LiveCameraFrame(gray, started_at + timedelta(seconds=30)),
        LiveCameraFrame(duplicate_orange, started_at + timedelta(seconds=60)),
    )

    def fake_decode(frame):
        if frame.path == orange:
            return bytes([255, 90, 20]) * 100
        return bytes([120, 120, 120]) * 100

    monkeypatch.setattr(afterglow_selector, "_decode_rgb", fake_decode)

    ranked = afterglow_selector.rank_afterglow_candidates(frames)

    assert [candidate.frame.path for candidate in ranked] == [orange, gray]
    assert ranked[0].local_score > ranked[1].local_score
