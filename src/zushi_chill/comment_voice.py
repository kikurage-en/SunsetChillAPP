from __future__ import annotations

import re

_STANDALONE_INTERJECTION = re.compile(
    r"(?:^|(?<=[。！？!?]))(?P<space>\s*)"
    r"(?P<word>わ[ぁあ]っ|あ+っ|やった|うわっ|ひええ|あれれ|えっ|おおっ|うーん|わくわく)"
    r"(?:っ?ピ)?"
    r"(?P<punct>[！!？?、,]+|…{2,}[。.]?)"
)
_BARE_A_INTERJECTION = re.compile(r"^(?P<word>あ+っ)(?:っ?ピ)?$")


def place_interjection_at_comment_start(text: str) -> str:
    """独立した感嘆詞をコメントの冒頭に1回だけ置く。"""
    matches = list(_STANDALONE_INTERJECTION.finditer(text))
    if not matches:
        return text

    first = matches[0]
    word = (
        "わあっ"
        if first.group("word") in {"わぁっ", "わあっ"}
        else first.group("word")
    )
    interjection = f"{word}{first.group('punct')}"
    body = text
    for match in reversed(matches):
        body = f"{body[: match.start()]}{body[match.end() :]}"
    return f"{interjection}{body.strip()}"


def apply_comment_voice(text: str) -> str:
    """Add the character suffix while leaving standalone interjections natural."""
    comment = text.strip()
    if not comment:
        return comment
    if bare_interjection := _BARE_A_INTERJECTION.fullmatch(comment):
        return f"{bare_interjection.group('word')}！"

    # モデルが「っピねぇ……」と語尾を重ねた場合は、明るい一語尾へ整える。
    # すでに二重化した「っピねぇっピ……」も同じ形へ戻す。
    comment = re.sub(
        r"っピね[ぇえ](?:っピ)?(?:…{2,}[。.]?|[。！？!?]+)",
        "っピ！",
        comment,
    )
    has_terminal_punctuation = bool(re.search(r"(?:[。！？!?]|…{2,})$", comment))

    protected: list[str] = []

    def protect_interjection(match: re.Match[str]) -> str:
        word = "わあっ" if match.group("word") in {"わぁっ", "わあっ"} else match.group("word")
        protected.append(f"{match.group('space')}{word}{match.group('punct')}")
        return f"\ue000{len(protected) - 1}\ue001"

    # 「わあっ！」のような独立した感嘆詞には、キャラクター語尾を付けない。
    comment = _STANDALONE_INTERJECTION.sub(protect_interjection, comment)

    # Put the suffix before an ellipsis so low-energy comments read as
    # 「むずかしいっピ……。」rather than「むずかしい……っピ。」.
    comment = re.sub(r"(?<!っピ)(…{2,})([。！？!?]?)", r"っピ\1\2", comment)
    comment = re.sub(r"(?<!っピ)(?<!…)([。！？!?]+)", r"っピ\1", comment)
    if not has_terminal_punctuation:
        comment = f"{comment}っピ。"

    for index, interjection in enumerate(protected):
        comment = comment.replace(f"\ue000{index}\ue001", interjection)
    return place_interjection_at_comment_start(comment)
