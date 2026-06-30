from __future__ import annotations

from datetime import date

from zushi_chill.config import Settings
from zushi_chill.sunset_eta import compute_sunset_eta, main


class _FakeClient:
    def __init__(self, payload: dict):
        self._payload = payload
        self.calls: list[dict] = []

    def fetch_forecast(self, **kwargs):
        self.calls.append(kwargs)
        return self._payload


def test_compute_sunset_eta_adds_offset_to_sunset(sample_payload):
    # 既定座標(逗子)/TZ(Asia/Tokyo)で十分。fixtureの日没は 2026-06-01T18:51。
    settings = Settings.from_env()
    client = _FakeClient(sample_payload)

    eta = compute_sunset_eta(
        settings, target_date=date(2026, 6, 1), offset_minutes=20, client=client
    )

    # 日没18:51 + 20分 = 19:11。日没連動でキャプチャ時刻が決まることを証明する。
    assert eta.strftime("%H:%M") == "19:11"
    assert eta.tzinfo is not None
    # 当日分の予報を取りに行く(target_date がフェッチへ伝わる)。
    assert client.calls[0]["target_date"] == date(2026, 6, 1)


def test_compute_sunset_eta_respects_custom_offset(sample_payload):
    settings = Settings.from_env()
    client = _FakeClient(sample_payload)

    eta = compute_sunset_eta(
        settings, target_date=date(2026, 6, 1), offset_minutes=30, client=client
    )

    # 日没18:51 + 30分 = 19:21。
    assert eta.strftime("%H:%M") == "19:21"


def test_main_prints_eta_to_stdout(sample_payload, monkeypatch, capsys):
    monkeypatch.setattr(
        "zushi_chill.sunset_eta.OpenMeteoClient",
        lambda **kwargs: _FakeClient(sample_payload),
    )

    exit_code = main(["--date", "2026-06-01", "--minutes", "20"])

    # VPS の at 予約が $() で取り込むため、stdout は HH:MM のみ。
    assert exit_code == 0
    assert capsys.readouterr().out.strip() == "19:11"


def test_main_returns_nonzero_when_fetch_fails(monkeypatch, capsys):
    class _FailingClient:
        def fetch_forecast(self, **kwargs):
            raise RuntimeError("Open-Meteo unavailable")

    monkeypatch.setattr(
        "zushi_chill.sunset_eta.OpenMeteoClient",
        lambda **kwargs: _FailingClient(),
    )

    exit_code = main(["--date", "2026-06-01"])

    # 予約計算が失敗したら非ゼロ終了し、stdout に HH:MM を出さない
    # (VPS 側の `RT=$(...) && ... | at $RT` で at 予約がスキップされる)。
    assert exit_code == 1
    assert capsys.readouterr().out.strip() == ""
