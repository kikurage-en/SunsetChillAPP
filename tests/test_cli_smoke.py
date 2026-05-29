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
        "GOOGLE_FORM_URL": "https://forms.example/cli",
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
    assert "逗子サンセットチル指数｜2026-06-01 13:00" in result.stdout
    assert "対象時間帯：17:21〜19:21" in result.stdout
    assert "https://forms.example/cli" in result.stdout

    rows = list(csv.DictReader(csv_path.open(encoding="utf-8")))
    assert len(rows) == 1
    assert rows[0]["date"] == "2026-06-01"
    assert rows[0]["line_sent"] == "False"
