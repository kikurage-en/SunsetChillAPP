from __future__ import annotations

import colorsys

from zushi_chill.sky_color import SKY_HEIGHT, SKY_WIDTH, in_sky, sky_color_score


def _image(top_rgb: tuple[int, int, int], bottom_rgb: tuple[int, int, int] = (90, 90, 90)) -> bytes:
    """水平線(上から64%)より上を空、下を海・砂浜として塗った画像。"""
    pixels = bytearray()
    for row in range(SKY_HEIGHT):
        color = top_rgb if row < SKY_HEIGHT * 0.64 else bottom_rgb
        for _ in range(SKY_WIDTH):
            pixels.extend(color)
    return bytes(pixels)


def _rgb(hue: float, saturation: float, value: float) -> tuple[int, int, int]:
    return tuple(round(channel * 255) for channel in colorsys.hsv_to_rgb(hue, saturation, value))


def test_sky_mask_excludes_buildings_headland_and_beach():
    assert in_sky(0.5, 0.3)
    assert in_sky(0.4, 0.6)  # 水平線すぐ上の中央
    assert not in_sky(0.1, 0.58)  # 左の建物
    assert not in_sky(0.85, 0.52)  # 右の岬
    assert not in_sky(0.5, 0.8)  # 海・砂浜


def test_orange_sky_scores_high_and_gray_dusk_scores_zero():
    orange = sky_color_score(_image(_rgb(0.06, 0.7, 0.7)))
    golden = sky_color_score(_image(_rgb(0.14, 0.6, 0.7)))
    blue = sky_color_score(_image(_rgb(0.6, 0.5, 0.7)))
    tinted_gray = sky_color_score(_image(_rgb(0.85, 0.1, 0.5)))

    assert orange > golden > 0
    assert blue == 0
    # 2026-07-24・09-21型: 曇天がカメラの色味で薄く紫がかっても色として数えない。
    assert tinted_gray == 0


def test_saturated_sun_glare_is_not_counted_as_colour():
    assert sky_color_score(_image(_rgb(0.06, 0.7, 0.98))) == 0


def test_colour_outside_the_sky_mask_is_ignored():
    # 海面の反射だけが橙色でも、空の指標には入れない。
    assert sky_color_score(_image((120, 140, 180), _rgb(0.06, 0.8, 0.7))) == 0
