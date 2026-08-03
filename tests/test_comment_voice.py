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


def test_apply_comment_voice_removes_suffix_from_long_a_interjection():
    assert apply_comment_voice("あああっピ！") == "あああっ！"


def test_apply_comment_voice_adds_punctuation_to_bare_long_a_interjection():
    assert apply_comment_voice("あああっピ") == "あああっ！"


def test_apply_comment_voice_only_suffixes_explanation_after_long_a_interjection():
    assert (
        apply_comment_voice("あああっピ！空がピンク色です！")
        == "あああっ！空がピンク色ですっピ！"
    )


def test_apply_comment_voice_normalizes_suffixed_interjection():
    assert apply_comment_voice("わぁっピ！") == "わあっ！"


def test_apply_comment_voice_only_suffixes_explanation_after_interjection():
    assert (
        apply_comment_voice("わぁっ！空が赤く光っています！")
        == "わあっ！空が赤く光っていますっピ！"
    )


def test_apply_comment_voice_normalizes_pi_nee_to_single_bright_suffix():
    assert (
        apply_comment_voice("わあっ！空がまだ、きれいなピンク色に染まってるっピねぇ……。")
        == "わあっ！空がまだ、きれいなピンク色に染まってるっピ！"
    )


def test_apply_comment_voice_repairs_already_duplicated_pi_nee_suffix():
    assert (
        apply_comment_voice("わあっ！空がまだ、きれいなピンク色に染まってるっピねぇっピ……。")
        == "わあっ！空がまだ、きれいなピンク色に染まってるっピ！"
    )


def test_apply_comment_voice_leaves_hesitation_without_suffix():
    assert apply_comment_voice("うーん……") == "うーん……"
