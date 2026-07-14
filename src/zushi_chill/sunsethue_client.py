"""Sunsethue API(ray-model の夕焼け品質予測)クライアント。

式・Vision とは独立したベンチマークをログ収集するための最小クライアント。スコアには
影響させない。Sunsethue は Cloudflare 配下で default の urllib User-Agent を bot 判定
(HTTP 403 / error 1010)で拒否するため、ブラウザ相当の User-Agent を必ず送る。認証は
API キーを ``key`` クエリパラメータで渡す(実測で確認済み)。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from datetime import date
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from zushi_chill.models import SunsethueResult

LOGGER = logging.getLogger(__name__)

SUNSETHUE_URL = "https://api.sunsethue.com/event"
# Cloudflare がブラウザ以外の UA を拒否するため、ブラウザ相当を送る。
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


class SunsethueError(RuntimeError):
    """Sunsethue の取得・解析に失敗したときに送出する。"""


def fetch_sunset_quality(
    *,
    latitude: float,
    longitude: float,
    target_date: date,
    api_key: str,
    timeout: int = 20,
) -> SunsethueResult:
    if not api_key:
        raise SunsethueError("SUNSETHUE_API_KEY is required")
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "date": target_date.isoformat(),
        "type": "sunset",
        "key": api_key,
    }
    url = f"{SUNSETHUE_URL}?{urlencode(params)}"
    request = Request(url, headers={"User-Agent": _USER_AGENT, "Accept": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise SunsethueError(f"Sunsethue returned HTTP {exc.code}: {body}") from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise SunsethueError(f"Sunsethue fetch failed: {exc}") from exc
    return _parse_event(payload)


def _parse_event(payload: Mapping[str, Any]) -> SunsethueResult:
    data = payload.get("data")
    if not isinstance(data, Mapping):
        raise SunsethueError("Sunsethue payload missing 'data' object")
    quality = data.get("quality")
    cloud_cover = data.get("cloud_cover")
    if not isinstance(quality, int | float) or not isinstance(cloud_cover, int | float):
        raise SunsethueError("Sunsethue 'quality'/'cloud_cover' missing or non-numeric")
    quality_text = data.get("quality_text")
    return SunsethueResult(
        quality=round(quality * 100),
        cloud_cover=round(cloud_cover * 100),
        quality_text=str(quality_text) if quality_text is not None else "",
    )
