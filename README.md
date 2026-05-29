# 逗子サンセットチル指数 MVP

逗子海岸の海の家スタッフ向けに、夕方の `Sunset期待度` と `Chill指数` を自動算出し、LINEグループへ投稿する内部検証用ツールです。一般公開向けの天気予報サービスではなく、2026年6月の目視検証とスコア調整を目的にしています。

外部向けには「天気予報」「確実に夕陽が見える」などの表現は使わず、「逗子サンセットチル指数」「夕方の来店参考指数」「Sunset期待度」などの表現を使います。

## セットアップ

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

実行環境は Python 3.12 以上を前提にしています。GitHub Actions でも Python 3.12 を指定しています。

`.env` または GitHub Secrets に以下を設定します。

```txt
LOCATION_NAME=逗子海岸
LATITUDE=35.2956
LONGITUDE=139.5736
TIMEZONE=Asia/Tokyo
LINE_CHANNEL_ACCESS_TOKEN=...
LINE_TARGET_ID=...
LIVE_CAMERA_URL=https://www.youtube.com/watch?v=Q5AAi9KOjG0
LIVE_CAMERA_VIDEO_ID=Q5AAi9KOjG0
LIVE_CAMERA_IMAGE_BASE_URL=https://<owner>.github.io/<repo>
LIVE_CAMERA_IMAGE_URL=
LIVE_CAMERA_PREVIEW_IMAGE_URL=
GOOGLE_FORM_URL=...
STORAGE_BACKEND=csv
CSV_PATH=logs/chill_predictions.csv
GOOGLE_SHEETS_SPREADSHEET_ID=...
GOOGLE_SHEETS_WORKSHEET=predictions
GOOGLE_SERVICE_ACCOUNT_JSON='{"type":"service_account",...}'
DRY_RUN=false
LOG_LEVEL=INFO
ALLOW_MISSING_HOURLY_FIELDS=
```

## LINE Messaging API

LINE Developers で Messaging API チャネルを作成し、チャネルアクセストークンを `LINE_CHANNEL_ACCESS_TOKEN` に設定します。送信先のユーザーID、グループID、または複数人チャットIDを `LINE_TARGET_ID` に設定します。

`LIVE_CAMERA_IMAGE_URL` または `LIVE_CAMERA_IMAGE_BASE_URL` が設定されている場合は、LINE本文に続けて画像メッセージも送信します。画像URLはLINEから取得できるHTTPS URLである必要があります。`LIVE_CAMERA_IMAGE_BASE_URL` を使う場合、画像URLは `live-camera/YYYY-MM-DD/HHMM.jpg` として組み立てます。

## ローカル実行

```bash
python -m zushi_chill.main --dry-run
python -m zushi_chill.main --dry-run --date 2026-06-01 --run-time 13:00
python -m zushi_chill.main --dry-run --input-json tests/fixtures/open_meteo_sample.json --date 2026-06-01 --run-time 13:00
python -m zushi_chill.main
```

`--dry-run` または `DRY_RUN=true` では LINE 送信を行わず、投稿文を標準出力に表示し、CSV に `line_sent=false` で保存します。
`--date YYYY-MM-DD` を指定した場合は、Open-Meteo の対象日にも `start_date/end_date` として渡します。
`--input-json` はOpen-Meteo APIを呼ばず、保存済みレスポンスJSONから算出します。ローカルの再現確認やfixtureを使った検証に使います。

Open-Meteo の必須変数に欠損がある場合は異常終了します。一部の欠損を許容したい場合は `ALLOW_MISSING_HOURLY_FIELDS=visibility,wind_gusts_10m` のように指定できます。許容したフィールドでも、評価時間帯の値がすべて欠損している場合は異常終了します。

## エラーハンドリング

Open-Meteo API取得は最大3回リトライし、最終失敗時は異常終了してLINE送信しません。必須変数の欠損、時刻形式不正、評価時間帯のデータ不足、非数値データも異常終了します。

通常実行では、まず `line_sent=false` の予測ログを保存してからLINE送信します。LINE送信に失敗した場合は、同じ `date`、`run_time`、`location_name` の行に `line_sent=false` と `error_message` を記録し、処理全体は異常終了扱いにします。

保存に失敗した場合、LINE送信前であればLINE送信しません。LINE送信後の保存更新に失敗した場合は、送信済みであることが分かるログを出して異常終了します。

## GitHub Actions

`.github/workflows/daily_chill.yml` は以下で実行されます。

- 04:07 / 04:22 / 04:37 UTC: 13:07 / 13:22 / 13:37 JST（LINE本文とログの `run_time` は 13:00）
- 08:07 / 08:22 / 08:37 UTC: 17:07 / 17:22 / 17:37 JST（LINE本文とログの `run_time` は 17:00）
- `workflow_dispatch`: GitHub UI から手動実行

定期実行では、GitHub Actions のscheduleイベント欠落に備えて各通知時刻に3回の起動機会を設けています。Actions の起動が数分遅れても通知本文とログの `run_time` が `13:00` / `17:00` になるように `--run-time` を自動指定します。既に同じ日付・時刻・地点で `line_sent=true` の記録がある場合は重複送信をスキップします。LINE本文ではこの時刻を表示し、各種数値は日没90分前から日没30分後までの対象時間帯の予測値を集計したものとして表示します。

LINE送信前に `LIVE_CAMERA_URL` のYouTubeライブから1フレームを取得し、GitHub Pagesへ `live-camera/YYYY-MM-DD/HHMM.jpg` としてデプロイします。ライブストリームURLを解決できない場合は、`LIVE_CAMERA_VIDEO_ID` からYouTubeのライブサムネイルを取得してフォールバックします。取得に成功した場合のみ、そのPages URLをLINE画像メッセージとして添付します。GitHub Pagesはリポジトリ設定でSourceを「GitHub Actions」にしておきます。Pages URLが標準の `https://<owner>.github.io/<repo>` と異なる場合は、Secret `LIVE_CAMERA_IMAGE_BASE_URL` で上書きします。

手動実行では `manual_mode`、`date`、`run_time` を指定できます。`manual_mode=dry_run` ではLINE送信せず保存処理まで確認し、`manual_mode=send_line` ではLINE送信と送信後の保存更新まで確認します。`date` は `YYYY-MM-DD`、`run_time` は `HH:MM` 形式です。

`STORAGE_BACKEND=csv` の場合、CSV は `CSV_PATH`（未指定時は `logs/chill_predictions.csv`）に保存され、Actions Artifact としてアップロードされます。`STORAGE_BACKEND=google_sheets` の場合は Google Sheets へ保存し、CSV Artifact は作成しません。

## Google Sheets 連携

CSV の代わりに Google Sheets へ保存する場合は、対象スプレッドシートをサービスアカウントのメールアドレスに共有し、以下を設定します。

```txt
STORAGE_BACKEND=google_sheets
GOOGLE_SHEETS_SPREADSHEET_ID=...
GOOGLE_SHEETS_WORKSHEET=predictions
GOOGLE_SERVICE_ACCOUNT_JSON='{"type":"service_account",...}'
```

指定ワークシートがない場合は自動作成します。ワークシートの1行目には保存カラムのヘッダーが自動で作られます。同じ `date`、`run_time`、`location_name` の行がある場合は、LINE送信結果を同じ行へ更新します。

## 6月の検証運用

1. 13:00 JST に昼時点の見込みを確認
2. 17:00 JST に夕方直前の見込みを確認
3. 日没前後に実際の空模様、夕焼け、快適度を確認
4. Googleフォームに `◎ / ○ / △ / ×` とメモ、必要に応じて写真を記録
5. 6月末に予測ログと実測評価の乖離を確認し、スコア式を調整

Googleフォームには、予測ログと突合しやすいように以下の項目を用意します。

- 日付
- 記録時刻
- 空模様評価: `◎ / ○ / △ / ×`
- 夕焼け評価: `◎ / ○ / △ / ×`
- 快適度評価: `◎ / ○ / △ / ×`
- 風の体感: `弱い / ちょうどよい / 強い`
- 蒸し暑さ: `なし / ややあり / かなりあり`
- 写真
- メモ

6月末には、`Sunset期待度80以上だが実測△/×`、`Sunset期待度50未満だが実測◎/○`、`Chill指数80以上だが快適度△/×`、`Chill指数50未満だが快適度◎/○` を重点的に確認します。乖離が大きい場合は、低層雲ペナルティ、高層雲ボーナス、中層雲ボーナス、湿度スコア、風スコア、降水リスク上限、Sunset期待度のChill指数への寄与率を見直します。

## スコア計算

`Sunset期待度` は 100 点から低層雲、降水、視程、強風のペナルティを引き、中層雲と高層雲の条件が良い場合にボーナスを加えます。視程 5,000m 未満では上限 50 に制限します。

`Chill指数` は体感温度、湿度、風、降水リスク、Sunset期待度を重み付きで合成します。降水確率、降水量、平均風速、突風、雨・雷雨系の天気コードに応じて上限を制限します。

`Sunset期待度` の初期式は以下です。

```txt
100
- 低層雲ペナルティ
- 降水ペナルティ
- 視程ペナルティ
- 強風ペナルティ
+ 中層雲ボーナス
+ 高層雲ボーナス
```

`Chill指数` の初期式は以下です。

```txt
体感温度スコア * 0.30
+ 湿度スコア * 0.20
+ 風スコア * 0.20
+ 降水リスクスコア * 0.20
+ Sunset期待度 * 0.10
```

強制上限は、降水確率70%以上でChill指数40、降水量1.0mm以上で45、平均風速8m/s以上で55、最大突風12m/s以上で50、雨・雷雨系の天気コードで45です。総合判定ラベルは `S=85〜100`、`A=70〜84`、`B=55〜69`、`C=40〜54`、`D=0〜39` です。

## テストと品質確認

```bash
ruff check .
pytest
```

スコア計算、ラベル境界、強制上限、メッセージ生成、Open-Meteo レスポンス解析、APIリトライ、dry-run CLI、CSV 保存、Google Sheets 保存アダプタをテストしています。LLM、画像生成、SNS投稿、自動最適化はMVPに含めていません。

## 今後の改善

- 6月の実測データに基づくスコア重み調整
- SNS向け短文や画像生成の検討
- Webカメラ画像解析や複数地点対応の検討
