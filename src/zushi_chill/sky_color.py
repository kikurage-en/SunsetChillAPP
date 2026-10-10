"""ライブカメラ画像の空の部分だけで夕焼け色を測る、AIを使わない画像代理指標。

日没時・残照の真値には同じVision LLM(Gemini)の採点を使ってきたが、2026-10-09の検証で
画素の色評価との順位相関が日没時0.21・残照0.58しかなく、どの予測信号が良いかが
ラベルの選び方で入れ替わった。予測と同じモデルに依存しない第2のラベルとして、
固定カメラの構図から空の領域だけを取り出し、橙・赤・紫の発色の強さと広がりを測る。

構図(2026-07〜10月で不変を確認): 水平線は画像の上から約64%、左に建物(上端約57%)、
右に岬(上端約50%)、最下部はモザイク処理。比率で指定するので解像度に依存しない。
"""

from __future__ import annotations

import colorsys
import subprocess
from pathlib import Path

SKY_WIDTH = 128
SKY_HEIGHT = 72
# 白飛び(太陽ディスクとその周辺)は色として数えない。
SATURATED_VALUE = 0.92
# 夕方の曇天はカメラの色味で薄く紫・桃色がかる。この程度の彩度は色として数えない
# (2026-07-24・09-21: 灰色の曇天で中位のスコアになり、目視・Geminiとも色なし)。
GRAY_SATURATION = 0.15


def sunset_hue_weight(hue: float) -> float:
    """HSV色相(0〜1)の重み。赤・橙・金色と、桃・紫を数え、青空と緑を除く。

    残照候補の選定(afterglow_selector)と違い、金色の焼け(色相0.13〜0.17)も数える
    (2026-09-15・10-03: 金色の焼けを目視・Geminiとも高く評価したのに低スコアだった)。
    """
    if hue >= 0.94 or hue <= 0.04:
        return 1.0
    if hue <= 0.13:
        return 1.0 - ((hue - 0.04) / 0.09) * 0.25
    if hue <= 0.17:
        return 0.75 * (0.17 - hue) / 0.04
    if 0.72 <= hue <= 0.94:
        return 0.75 + ((hue - 0.72) / 0.22) * 0.25
    return 0.0


def in_sky(x_fraction: float, y_fraction: float) -> bool:
    """画像座標(0〜1)が空の領域か。建物・岬・海面・砂浜を除く。"""
    if y_fraction < 0.48:
        return True
    if x_fraction < 0.25:
        return y_fraction < 0.55
    if x_fraction <= 0.66:
        return y_fraction < 0.62
    return False


def decode_rgb(path: Path, *, width: int = SKY_WIDTH, height: int = SKY_HEIGHT) -> bytes:
    completed = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(path),
            "-vf",
            f"scale={width}:{height}",
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "pipe:1",
        ],
        check=False,
        capture_output=True,
        timeout=30,
    )
    expected = width * height * 3
    if completed.returncode != 0 or len(completed.stdout) != expected:
        error = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"Could not decode {path}: {error or completed.returncode}")
    return completed.stdout


def sky_color_score(
    pixels: bytes, *, width: int = SKY_WIDTH, height: int = SKY_HEIGHT
) -> float:
    """空の領域の夕焼け色を0〜100で返す(強さの平均と、鮮やかな画素の割合)。"""
    if len(pixels) != width * height * 3:
        raise ValueError("Pixel buffer does not match the image size")
    strength_sum = 0.0
    vivid = 0
    count = 0
    for row in range(height):
        y_fraction = (row + 0.5) / height
        for column in range(width):
            if not in_sky((column + 0.5) / width, y_fraction):
                continue
            offset = (row * width + column) * 3
            red, green, blue = (channel / 255.0 for channel in pixels[offset : offset + 3])
            hue, saturation, value = colorsys.rgb_to_hsv(red, green, blue)
            count += 1
            if value >= SATURATED_VALUE or value < 0.08:
                continue
            exposure = min(value / 0.3, 1.0) ** 2
            chroma = max(0.0, (saturation - GRAY_SATURATION) / (1.0 - GRAY_SATURATION))
            strength = sunset_hue_weight(hue) * chroma * exposure
            strength_sum += strength
            if strength >= 0.3:
                vivid += 1
    if count == 0:
        raise ValueError("Sky mask selected no pixels")
    return round(min(100.0, 100.0 * (2.2 * strength_sum / count + 0.35 * vivid / count)), 2)


def score_image(path: Path) -> float:
    return sky_color_score(decode_rgb(path))
