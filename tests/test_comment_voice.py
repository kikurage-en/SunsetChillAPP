from zushi_chill.comment_voice import apply_comment_voice


def test_apply_comment_voice_adds_suffix_to_each_sentence():
    assert (
        apply_comment_voice("水平線にすきまがあります。雲も色づきそうです！")
        == "水平線にすきまがありますっピ。雲も色づきそうですっピ！"
    )


def test_apply_comment_voice_places_suffix_before_ellipsis():
    assert (
        apply_comment_voice("夕焼けの色は消えちゃったみたい……。")
        == "夕焼けの色は消えちゃったみたいっピ……。"
    )


def test_apply_comment_voice_does_not_duplicate_existing_suffix():
    assert apply_comment_voice("やったっピ！") == "やったっピ！"
