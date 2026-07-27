# 逗子サンセットチル指数 現行要件

最終更新: 2026-07-27

この文書は現在の機能要件と受け入れ条件を定義する。操作・セットアップ手順は
`README.md`、本番反映状況と前向き検証の判断は `STATUS.md`、スコア閾値と保存カラムの
厳密な定義はコードとテストを正とする。

## 1. 目的と位置づけ

逗子海岸の海の家スタッフ向けに、夕方の `Sunset期待度` と `Chill指数` を算出し、
LINEグループへ通知する。一般公開向けの気象予報サービスではなく、気象式・ライブ
カメラAI・外部ベンチマークを比較しながら精度を改善する内部検証用ツールとする。

外部向けには「天気予報」「確実に夕陽が見える」などの断定表現を避け、
「逗子サンセットチル指数」「夕方の来店参考指数」「Sunset期待度」を使用する。

## 2. 対象範囲

### 2.1 実装対象

- Open-Meteoから逗子海岸と日没方位側の気象データを取得する。
- 気象庁から神奈川県東部の6時間降水確率を取得する。
- 当日の日没時刻と、日没90分前〜30分後の評価時間帯を算出する。
- `Sunset期待度` と `Chill指数` を0〜100で算出する。
- 日没前のライブカメラ画像をVision LLMで解析し、表示用Sunset期待度へブレンドする。
- 日没時と日没後の画像を自動取得し、発色と残照を人手なしで別評価する。
- Sunsethue APIの予測をlog-onlyの独立ベンチマークとして保存する。
- LINE Messaging APIでテキストと、取得できた場合はライブカメラ画像を送信する。
- Google SheetsまたはCSVへ予測・画像評価・送信結果を保存する。
- GitHub Actionsの `workflow_dispatch` を、Contaboのcronまたは永続観測スケジューラから
  起動する。
- pytestとruffで主要な契約とロジックを検証する。

### 2.2 対象外

- Instagram、X、TikTokなどへの自動投稿
- SNS投稿用画像の生成
- 一般利用者向けWebアプリ・管理画面
- 複数地点対応
- 課金・ユーザー認証
- 機械学習による自動的な重み更新
- 人手による日次の夕焼け評価入力

## 3. 気象データとスコア

### 3.1 Open-Meteo

Forecast APIから次のhourly変数と `daily.sunset` を取得する。

```txt
temperature_2m
relative_humidity_2m
apparent_temperature
precipitation_probability
precipitation
weather_code
cloud_cover
cloud_cover_low
cloud_cover_mid
cloud_cover_high
visibility
wind_speed_10m
wind_direction_10m
wind_gusts_10m
```

評価時間帯では気温・体感温度・湿度・雲量・風速を平均、降水確率・突風を最大、
降水量を合計、視程を最小で集計する。Open-Meteoが直前1時間値として定義する降水確率・
降水量・突風は、hourlyのタイムスタンプを区間終端として評価時間帯との重なりを判定する。
必須値の欠損・非数値・評価対象不足は異常終了し、
`ALLOW_MISSING_HOURLY_FIELDS` で指定したフィールドだけ欠損を許容する。

校正用として、日没時刻を挟む直前のhourly行と最初のhourly行について、降水確率・
降水量・天気コード・視程を集計値とは別に保存する。日没18:54の場合は18:00を
`before_sunset`、19:00を `at_sunset` とする。

### 3.2 気象庁降水確率

気象庁の神奈川県予報区JSONから一次細分区域「東部」の6時間降水確率を取得する。
これは予報区内で対象期間に1mm以上の雨が降る確率であり、LINEの現地天気参考値と
Chill指数の降水リスクへ使用する。取得失敗、対象期間欠測、オフライン再現時は非致命とし、
Open-Meteoの評価時間帯最大降水確率へフォールバックする。

### 3.3 Sunset期待度

- 低層雲、降水、視程、強風を減点する。
- 中層雲と高層雲が適量の場合は加点する。
- 遮蔽側の低層雲・総雲量は日没方位40km地点を既定とする。
- 発色源の中層雲・高層雲は日没方位20km地点を既定とする。
- 遠地点取得失敗時は逗子、近地点取得失敗時は遠地点へフォールバックする。
- 厚い総雲量・中層雲・低視程・降水条件では上限を適用する。
- 評価時間帯の代表天気コードが雨・雷雨系、または窓内予想雨量合計1.0mm以上
  (雨シグナル)では上限40を適用する。減点は予想雨量に比例させない。
- 降水確率80%以上でも、評価時間帯の予想雨量0、晴天コード0/1、西側総雲量50%未満、
  西側低層雲30%未満が同時成立する場合は、予報信号の不一致として降水減点を暫定-25とする。
  この条件は「雨なし」の断定ではなく、夕焼け予測の不確実性が高いことも本文へ表示する。
- 通常の天井は80、超快晴条件のみ90まで許容する。
- 降水条件には、地点・時間粒度が夕焼けイベントに近いOpen-Meteoの評価時間帯値を使う。
  気象庁値は6時間・予報区単位のためSunset期待度へは混ぜず、前向き比較用に保存する。

厳密な閾値は `src/zushi_chill/scoring.py` とその回帰テストを正とする。

### 3.4 Chill指数

体感温度30%、湿度20%、風20%、降水リスク20%、純式のSunset期待度10%で合成する。
降水リスクには気象庁の6時間降水確率を優先し、欠測時だけOpen-Meteoを使う。
降水、雨・雷雨系天気コード、強風・突風、低体感温度、厚い雲では上限を適用する。
VisionブレンドはChill指数へ影響させない。

### 3.5 表示用Sunset期待度

日没前にVision解析が成功した場合のみ、純式 `sunset_score` と
`vision_sunset_score` を `SUNSET_VISION_BLEND_WEIGHT` で合成し、
`final_sunset_score` として表示する。既定のVision重みは0.8とし、Visionによる上方修正は
純式+30までに制限する。雨シグナル(3.3)の実行では上方修正を無効化し、
`final_sunset_score ≤ sunset_score` とする。下方修正は制限しない。

純式 `sunset_score` は上書きしない。日没時・残照フェーズ、Vision欠測、重み0では、
`final_sunset_score = sunset_score` とする。

## 4. ライブカメラ画像評価

### 4.1 評価フェーズ

要求された `run_time` と当日の日没時刻から次のフェーズを決める。

| フェーズ | 時刻 | 用途 |
|---|---|---|
| `predict` | 日没前 | 雲構造から日没時の夕焼けを予測 |
| `sunset` | 日没時〜+10分 | 太陽ディスクの見えやすさと日没時の発色を別評価 |
| `afterglow` | 日没+10分より後 | 残照だけを評価 |

日没時は `vision_sun_disk_visibility` と `vision_sunset_color_score`、日没+20分は
`vision_afterglow_score` を記録する。`vision_sunset_score` は後方互換の総合値として残す。

これらは同じVision LLMによる画像代理指標であり、独立したground truthとは扱わない。
予測との誤差は日没時の発色と残照で別々に集計する。

### 4.2 画像取得と保存

- 日没連動ジョブはContaboでYouTubeライブから1フレームを取得し、取得時刻を確定する。
- 取得画像はContaboの永続spoolへ固定し、45KB以下のJPEGへ正規化する。
- 固定画像をBase64形式のworkflow inputとしてSHA-256と一緒にGitHub Actionsへ渡し、
  Actions側でハッシュを照合してから使用する。
- 13:00 / 17:00と手動ジョブはGitHub Actionsで1フレームを取得する。
- ストリーム解決に失敗した場合はYouTubeライブサムネイルへフォールバックする。
- 取得画像をGitHub Pagesへ公開し、LINE画像メッセージに使用する。
- 取得に成功した画像をActions Artifactへ90日指定で保存する。
- Artifact名と画像パスには対象日と `run_time` を含める。
- 日没連動ジョブでは画像取得・保存失敗をジョブ失敗として再試行し、空の観測行を
  完了扱いにしない。Vision解析失敗は非致命とする。

保存画像を別モデルで一括再採点する専用CLIは現時点では実装対象外とする。Artifactは
将来の再採点元データとして保持する。

## 5. 実行スケジュール

GitHub Actions自身には `schedule` を持たせず、`workflow_dispatch` だけを公開する。
13:00 / 17:00はContaboのcron、日没連動の2件はsystemd timerから起動する。

| 時刻 | `manual_mode` | LINE | 用途 |
|---|---|---|---|
| 13:00 | `send_line` | 送信 | 昼時点の見込み |
| 17:00 | `send_line` | 送信 | 夕方直前の見込み・カメラAI予測 |
| 当日の日没時 | `dry_run` | 送信しない | 日没時画像の評価・保存 |
| 日没+20分 | `send_line` | 送信 | 残照評価・通知 |

日没連動の2件はAstralによるネットワーク非依存の日没計算と、SQLiteの永続ジョブを使う。
systemd timerは毎分ジョブを確認し、予定時刻を過ぎた未実行ジョブを追いつき実行する。
撮影画像は最初の成功時に固定し、以後のOpen-Meteo・GitHub・Vision・保存失敗では同じ画像で
再試行する。ジョブ状態は再起動後も保持し、GitHub Actions成功を確認するまで完了にしない。
撮影前の停止が既定60分を超えた場合は過去画像を捏造せず `capture_missed` として監査に残す。

同一観測は `observation_id` で保存・送信済み判定を行う。LINE Pushには観測単位の
`X-Line-Retry-Key` を付け、同夜のワークフロー再実行による重複送信を防ぐ。LINE側の
再送キー保持期間を超える前に通知再試行を止め、以後は `dry_run` でログだけを回復する。

## 6. LINE通知

- LINE Messaging APIのPush messageを使用する。
- 本文冒頭は `YYYY-MM-DD HH:MM` だけを表示し、サービス名や括弧を付けない。
- 表示値には `final_sunset_score`、Chill指数には純式 `sunset_score` を使用する。
- Vision解析がある場合は予測・日没時評価・残照評価のラベルを区別する。
- 日没時評価では太陽ディスクと発色、残照評価では残照の個別値を本文へ含める。
- 画像URLが利用できる場合はテキストと画像を送信し、なければテキストだけ送信する。
- 日没時の `dry_run` は本文生成と保存まで行い、通常通知・失敗通知ともLINEへ送信しない。
- 日没前の天気参考欄は、日没時刻に最も近いhourly行の気温・湿度・風・夕焼け方向の
  層別雲量・視程を表示する。最寄りhourly時刻はログに保存し、本文へは表示しない。
  日没時・残照フェーズは従来どおり実行時刻付近の気温と対象時間帯集計値を表示する。
- 対象時間帯、体感温度、突風、降水確率の期間・区域・出典は本文に表示しない。
- 降水確率は気象庁値を優先し、欠測時はOpen-Meteoの対象時間帯最大値を表示する。
- コメントは現地確認を依頼せず、表示用Sunset期待度とChill指数の予測水準を文章化する。
  気象要因の補足は優先度が最も高い1件に制限する。
- 日没前のコメントは予測表現とし、日没時・残照フェーズでは「見込み」などの予測表現を
  使わず、その時点の条件として表現する。
- 高い降水確率と雨量・晴天コード・西空の薄い雲が食い違う場合は、予測の不確実性が
  高い旨をコメントへ含める。

## 7. 保存要件

### 7.1 保存先と更新

`STORAGE_BACKEND` でGoogle SheetsまたはCSVを選択する。通常実行ではLINE送信前に
`line_sent=false` で保存し、送信結果を同じ `date`、`run_time`、`location_name` の行へ
反映する。

Google Sheetsは旧ヘッダーが新ヘッダーのprefixと一致する場合に自動移行する。
既存CSVはヘッダーを自動変更せず、不一致時は `ConfigError` とする。

### 7.2 保存カラム

保存スキーマは次の74列とし、順序は `src/zushi_chill/storage.py` の `CSV_COLUMNS` を正とする。

```txt
date
run_time
location_name
latitude
longitude
sunset_time
target_window_start
target_window_end
chill_score
chill_label
sunset_score
sunset_label
temperature_2m
apparent_temperature
relative_humidity_2m
precipitation_probability
precipitation
weather_code
cloud_cover
cloud_cover_low
cloud_cover_mid
cloud_cover_high
visibility
wind_speed_10m
wind_direction_10m
wind_gusts_10m
comment
line_sent
error_message
vision_sunset_score
vision_sky_condition
vision_comment
vision_model
sunset_cloud_cover
sunset_cloud_cover_low
sunset_cloud_cover_mid
sunset_cloud_cover_high
final_sunset_score
final_sunset_label
sunsethue_quality
sunsethue_cloud_cover
sunsethue_quality_text
vision_evaluation_phase
vision_sun_disk_visibility
vision_sunset_color_score
vision_afterglow_score
precipitation_probability_before_sunset
precipitation_before_sunset
weather_code_before_sunset
visibility_before_sunset
precipitation_probability_at_sunset
precipitation_at_sunset
weather_code_at_sunset
visibility_at_sunset
jma_precipitation_probability
jma_precipitation_period_start
jma_precipitation_period_end
jma_precipitation_area
jma_report_time
sunset_snapshot_time
temperature_2m_at_sunset
relative_humidity_2m_at_sunset
visibility_at_sunset_snapshot
wind_speed_10m_at_sunset
wind_direction_10m_at_sunset
sunset_cloud_cover_low_at_sunset
sunset_cloud_cover_mid_at_sunset
sunset_cloud_cover_high_at_sunset
observation_id
observation_phase
scheduled_at
captured_at
capture_delay_seconds
observation_data_quality
```

## 8. Sunsethueベンチマーク

`SUNSETHUE_ENABLED=true` かつAPIキーがある場合、逗子海岸の座標をSunsethueへ渡し、
`quality`、`cloud_cover`、`quality_text` を保存する。Sunsethueは式・Visionと独立した
log-only信号とし、Sunset期待度・Chill指数・表示値を変更しない。失敗は非致命とする。

## 9. エラーハンドリング

- Open-Meteoは最大3回リトライし、最終失敗時はLINEを送らず異常終了する。
- 日没連動ジョブのOpen-Meteo・GitHub Actions・保存失敗は、固定済み画像を使って再試行する。
- LINE送信前の保存失敗時はLINEを送信しない。
- LINE送信失敗時は `line_sent=false` とエラー内容を保存して異常終了する。
- LINE送信後の保存更新失敗は送信済みであることをログへ出して異常終了する。
- Vision、画像取得、Sunsethue、気象庁降水確率の失敗は警告を記録して処理を継続する。
- シークレット値をコード・ログ・リポジトリへ保存しない。
- 21:30 JSTの監査で当日の未完了ジョブがあれば非ゼロ終了し、systemd journalに状態と
  最終エラーを残す。

## 10. 設定

環境変数の全一覧と既定値は `.env.example` を正とする。GitHub Actionsではシークレットを
環境変数へ渡し、Contaboではリポジトリ直下の `.env` を読み込む。

Vision画像評価には `VISION_ENABLED=true` と `VISION_API_KEY` が必要である。
`VISION_TARGET_HOURS` の既定 `16,17,18,19` は、逗子の日没時と日没+20分を通年で
カバーする。

永続観測スケジューラは `OBSERVATION_DB_PATH`、`OBSERVATION_SPOOL_DIR`、
`AFTERGLOW_OFFSET_MINUTES`、`OBSERVATION_CAPTURE_MAX_DELAY_MINUTES`、
`OBSERVATION_RUN_VISIBILITY_GRACE_SECONDS`、`OBSERVATION_RETRY_MAX_SECONDS` で設定する。

## 11. テスト・受け入れ条件

- `ruff check .` が成功する。
- `pytest` が成功する。
- スコア境界、強制上限、層別雲量、Visionブレンド上限を回帰テストする。
- Visionの3フェーズ、個別画像評価値、旧形式応答の互換性をテストする。
- CSVの74列出力とGoogle Sheetsの旧ヘッダー・列幅移行をテストする。
- 気象庁6時間降水確率の期間選択、LINE表示、Chill優先利用、Sunset非利用をテストする。
- 日没前のLINE予測が日没時刻に最も近いhourly気温・湿度・風・層別雲量・視程を表示し、
  Sunset期待度・Chill指数は対象時間帯集計のまま変わらないことをテストする。
- 日没時・残照フェーズのコメントに予測表現が残らないことをテストする。
- コメントが両指数の組み合わせと主要気象要因を反映し、現地確認依頼を含まないことを
  テストする。
- 2026-07-21型の条件付き降水減点と、2026-07-16型へ緩和が誤適用されないことを
  回帰テストする。
- 日没時と日没+20分のローカル日没計算、永続ジョブ、追いつき実行、同一画像での
  再試行、監査をテストする。
- GitHub Actionsの固定画像取得、Artifact保存、Pages公開、dry-run/send-line分岐を検証する。
- dry-runでは通常通知・失敗通知ともLINEへ送らず、通常実行では送信結果を保存する。
- 画像・Vision・Sunsethueの非致命エラーで主要処理が継続する。

## 12. 法務・表現上の注意

本ツールは内部検証用とし、外部向けに「天気予報」「気象予報」「確実に夕陽が見える」
などの断定表現を使用しない。一般公開・継続運用へ移行する場合は、必要に応じて
気象業務法、予報業務許可、気象予報士関与の要否を確認する。

## 13. 今後の候補

- 保存Artifactを対象にした一括再採点CLI
- 画像代理指標のモデル間比較と評価基準の固定
- サンプル蓄積後の主予測信号選抜
- 高降水確率・雨量0型を同型N≥10で再評価する。日没前後の診断8列、日没時の発色、
  +20分の残照、保存画像を同日単位で突合し、補正後の純式が画像代理値を20点以上
  上回る例が3件に達した場合はN=10を待たず見直す。
- 気象庁値とOpen-Meteo値が同時にN≥10蓄積した時点で、Sunset画像代理値に対する
  識別力を前向き比較する。履歴に気象庁発表値がないため、現時点では遡及比較しない。
- 残照光路の遠方雲サンプリング
- 複数地点対応、管理画面、来店実績との相関分析
- SNS向け短文・画像生成（公開運用の判断後）
