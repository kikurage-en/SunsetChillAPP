from __future__ import annotations

import re


def apply_comment_voice(text: str) -> str:
    """Ensure every Japanese sentence ends in the notification character's voice."""
    comment = text.strip()
    if not comment:
        return comment

    # Put the suffix before an ellipsis so low-energy comments read as
    # 「むずかしいっピ……。」rather than「むずかしい……っピ。」.
    comment = re.sub(r"(?<!っピ)(…{2,})([。！？]?)", r"っピ\1\2", comment)
    comment = re.sub(r"(?<!っピ)(?<!…)([。！？]+)", r"っピ\1", comment)
    if not re.search(r"[。！？]$", comment):
        comment = f"{comment}っピ。"
    return comment
