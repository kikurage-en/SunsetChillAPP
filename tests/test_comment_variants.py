from __future__ import annotations

import pytest

from zushi_chill.comment_variants import select_comment_variant

VARIANTS = ("ひとつめ", "ふたつめ", "みっつめ")


def test_select_comment_variant_is_stable_for_same_observation():
    first = select_comment_variant("2026-07-29", "17:00", "headline", VARIANTS)
    repeated = select_comment_variant("2026-07-29", "17:00", "headline", VARIANTS)

    assert first == repeated


def test_select_comment_variant_changes_on_consecutive_dates():
    first = select_comment_variant("2026-07-28", "17:00", "headline", VARIANTS)
    next_day = select_comment_variant("2026-07-29", "17:00", "headline", VARIANTS)

    assert first != next_day


def test_select_comment_variant_changes_between_13_and_17():
    at_13 = select_comment_variant("2026-07-29", "13:00", "headline", VARIANTS)
    at_17 = select_comment_variant("2026-07-29", "17:00", "headline", VARIANTS)

    assert at_13 != at_17


def test_select_comment_variant_rejects_empty_bank():
    with pytest.raises(ValueError, match="must not be empty"):
        select_comment_variant("2026-07-29", "17:00", "headline", ())
