from __future__ import annotations

import csv
import os
import subprocess
import sys
from pathlib import Path


def test_python_module_cli_dry_run_with_fixture(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    csv_path = tmp_path / "cli.csv"
    env = {
        **os.environ,
        "PYTHONPATH": str(repo_root / "src"),
        "STORAGE_BACKEND": "csv",
        "CSV_PATH": str(csv_path),
    }

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "zushi_chill.main",
            "--dry-run",
            "--input-json",
            str(repo_root / "tests" / "fixtures" / "open_meteo_sample.json"),
            "--date",
            "2026-06-01",
            "--run-time",
            "13:00",
        ],
        cwd=repo_root,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stdout.startswith("2026-06-01 13:00\n")
    assert "逗子サンセットチル指数｜" not in result.stdout
    assert "日没：18:51" in result.stdout
    assert "最寄り予報" not in result.stdout
    assert "気温：22.0℃" in result.stdout
    assert "湿度：72%" in result.stdout
    assert "風：南 4.0m/s" in result.stdout
    assert "低層 25% / 中層 40% / 高層 55%" in result.stdout
    assert "対象時間帯：" not in result.stdout
    assert "夕焼け方向の雲" in result.stdout

    rows = list(csv.DictReader(csv_path.open(encoding="utf-8")))
    assert len(rows) == 1
    assert rows[0]["date"] == "2026-06-01"
    assert rows[0]["line_sent"] == "False"


def test_python_module_cli_after_sunset_uses_actual_comment_tense(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    env = {
        **os.environ,
        "PYTHONPATH": str(repo_root / "src"),
        "STORAGE_BACKEND": "csv",
        "CSV_PATH": str(tmp_path / "after-sunset.csv"),
    }

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "zushi_chill.main",
            "--dry-run",
            "--input-json",
            str(repo_root / "tests" / "fixtures" / "open_meteo_sample.json"),
            "--date",
            "2026-06-01",
            "--run-time",
            "19:14",
        ],
        cwd=repo_root,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    comment = result.stdout.split("コメント：\n", 1)[1].split("\n\n日没：", 1)[0]
    assert "空の色は大当たりっピ！" in comment
    assert "海辺" not in comment
    assert len(comment.splitlines()) == 1
    assert "良好な見込みです" not in result.stdout
