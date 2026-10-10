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


def test_apply_comment_voice_moves_mid_comment_interjection_to_start():
    assert (
        apply_comment_voice("空が薄く染まっています。わぁっ！富士山も見えます。")
        == "わあっ！空が薄く染まっていますっピ。富士山も見えますっピ。"
    )


def test_apply_comment_voice_moves_comma_interjection_to_start():
    assert (
        apply_comment_voice("夕焼けは楽しみです。わぁっ、高い雲が見えます。")
        == "わあっ、夕焼けは楽しみですっピ。高い雲が見えますっピ。"
    )


def test_apply_comment_voice_keeps_only_one_interjection_at_start():
    assert (
        apply_comment_voice("やった！空が染まっています。わあっ！富士山も見えます。")
        == "やった！空が染まっていますっピ。富士山も見えますっピ。"
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


def test_apply_comment_voice_does_not_duplicate_suffix_after_sentence_particle():
    # 2026-09-23 17:51 残照: 「見えないっピねっピ……。」と語尾が重なっていた。
    assert apply_comment_voice("夕焼け色は見えないっピね……。") == "夕焼け色は見えないっピ……。"
    assert apply_comment_voice("夕焼け色が残ってるっピよ！") == "夕焼け色が残ってるっピ！"
    assert (
        apply_comment_voice("空は雲に覆われてるっピ。夕焼け色は見えないっピねっピ……。")
        == "空は雲に覆われてるっピ。夕焼け色は見えないっピ……。"
    )


def test_apply_comment_voice_skips_suffix_for_mid_sentence_pause():
    # 2026-10-08 17:00: 「水平線はっピ……少しクリア」になっていた。
    assert (
        apply_comment_voice("水平線は……少しクリアに見える")
        == "水平線は……少しクリアに見えるっピ。"
    )


def test_apply_comment_voice_treats_un_as_standalone_interjection():
    # 2026-09-17 17:46: 「うんっピ……、」と感嘆詞に語尾が付いていた。
    assert apply_comment_voice("うん……、空が少し色づいてる。") == "うん……、空が少し色づいてるっピ。"
