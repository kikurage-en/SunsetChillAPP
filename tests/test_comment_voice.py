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


def test_apply_comment_voice_removes_suffix_from_standalone_interjection():
    assert apply_comment_voice("やったっピ！") == "やった！"


def test_apply_comment_voice_leaves_standalone_interjection_without_suffix():
    assert apply_comment_voice("わぁっ!") == "わあっ!"


def test_apply_comment_voice_normalizes_suffixed_interjection():
    assert apply_comment_voice("わぁっピ！") == "わあっ！"


def test_apply_comment_voice_only_suffixes_explanation_after_interjection():
    assert (
        apply_comment_voice("わぁっ！空が赤く光っています！")
        == "わあっ！空が赤く光っていますっピ！"
    )


def test_apply_comment_voice_leaves_hesitation_without_suffix():
    assert apply_comment_voice("うーん……") == "うーん……"
