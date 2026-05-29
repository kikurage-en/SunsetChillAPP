from __future__ import annotations

from datetime import datetime


def build_capture_relative_path(run_time: datetime) -> str:
    return f"live-camera/{run_time.date().isoformat()}/{run_time.strftime('%H%M')}.jpg"


def build_capture_url(base_url: str, relative_path: str) -> str:
    normalized_base_url = base_url.strip().rstrip("/")
    normalized_path = relative_path.strip().lstrip("/")
    if not normalized_base_url:
        return ""
    return f"{normalized_base_url}/{normalized_path}"
