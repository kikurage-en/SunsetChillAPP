# 2026-07-30 逗子海岸シークレット花火監視

SunsetChillの定期予測とは独立した、一日限りの監視ジョブです。

## 本番動作

YouTubeはデータセンターIPからのHLS取得をBot判定で拒否するため、映像取得と秘密情報を
次のように分離します。

1. AC接続したローカルMacが19:30〜20:30の逗子海岸ライブ映像を2fpsで監視する。
   配信切断時はHLS URLを再取得し、5秒間隔で終了時刻まで再開を試みる。
2. 夜空の局所的な発光から、スコア上位30枚の候補をローカルに保存する。
   明るい変化が途切れない映像でも8秒ごとに候補を確定し、切断前の候補も破棄しない。
3. 候補を`pages-images`ブランチの`fireworks-candidates/2026-07-30/`へ一括保存する。
4. ローカル収集プロセスが`Fireworks Watch 2026-07-30`を起動する。
5. GitHub Actions内のGemini Visionが実際の花火かを確認し、品質上位6枚を選ぶ。
   全候補の解析に失敗した場合は「花火なし」ではなく監視エラーを通知する。
6. LINEコメントは定期通知と同じ`apply_comment_voice()`を通し、全ての文末を「っピ」にする。

GitHub Actions側はYouTubeへ接続せず、Vision・LINEのSecretもローカルMacへ移しません。
花火を確認できなかった場合、またはローカル監視に失敗した場合もLINEへ状態を通知します。

## 手動テスト

Actionsの`Fireworks Watch 2026-07-30`は既定が`dry_run`で、LINE送信を行いません。
`candidate_paths`には`pages-images`上の候補パスをJSON配列で渡します。`send_line`は
本番送信なので、疎通確認だけを目的に選択しないでください。

## イベント後

ローカルの`caffeinate`プロセスと一時的な`pages-images` checkoutを終了・削除し、
`.github/workflows/fireworks_watch_20260730.yml`を削除します。保存画像は記録として
`pages-images`ブランチに残します。
