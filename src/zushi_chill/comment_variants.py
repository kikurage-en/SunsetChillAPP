from __future__ import annotations

from datetime import date


def select_comment_variant(
    day: str,
    run_time: str,
    category: str,
    variants: tuple[str, ...],
) -> str:
    """Choose a reproducible variant without repeating adjacent scheduled runs."""
    if not variants:
        raise ValueError("comment variants must not be empty")
    hour = int(run_time.split(":", maxsplit=1)[0])
    day_ordinal = date.fromisoformat(day).toordinal()
    if run_time == "13:00":
        observation_slot = day_ordinal * 2
    elif run_time == "17:00":
        observation_slot = day_ordinal * 2 + 1
    else:
        observation_slot = day_ordinal + hour
    category_offset = sum(
        position * ord(character)
        for position, character in enumerate(category, start=1)
    )
    index = (observation_slot + category_offset) % len(variants)
    return variants[index]
