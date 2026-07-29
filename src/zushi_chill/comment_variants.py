from __future__ import annotations

from datetime import date


def select_comment_variant(
    day: str,
    run_time: str,
    category: str,
    variants: tuple[str, ...],
) -> str:
    """Choose a reproducible variant that rotates by date and execution hour."""
    if not variants:
        raise ValueError("comment variants must not be empty")
    hour = int(run_time.split(":", maxsplit=1)[0])
    category_offset = sum(
        position * ord(character)
        for position, character in enumerate(category, start=1)
    )
    index = (date.fromisoformat(day).toordinal() + hour + category_offset) % len(
        variants
    )
    return variants[index]
