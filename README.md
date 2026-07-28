# 逗子サンセットチル指数 MVP

逗子海岸の海の家スタッフ向けに、夕方の `Sunset期待度` と `Chill指数` を自動算出し、LINEグループへ投稿する内部検証用ツールです。一般公開向けの天気予報サービスではなく、気象式・ライブカメラAI・外部ベンチマークを継続比較してスコアを改善することを目的にしています。日々の夕焼け評価は人手入力を前提とせず、保存したライブカメラ画像から自動記録します。

外部向けには「天気予報」「確実に夕陽が見える」などの表現は使わず、「逗子サンセットチル指数」「夕方の来店参考指数」「Sunset期待度」などの表現を使います。

現在の検証運用ステータス（本番構成・前向き検証の進捗・保留中の判断）は [`STATUS.md`](STATUS.md) を参照してください。

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
LINE_CHANNEL_SECRET=...
LINE_BOT_USER_ID=...
LIVE_CAMERA_URL=https://www.youtube.com/watch?v=Q5AAi9KOjG0
LIVE_CAMERA_VIDEO_ID=Q5AAi9KOjG0
LIVE_CAMERA_IMAGE_BASE_URL=https://<owner>.github.io/<repo>
LIVE_CAMERA_IMAGE_URL=
LIVE_CAMERA_PREVIEW_IMAGE_URL=
LIVE_CAMERA_PUBLIC_DIR=public
LIVE_CAMERA_CAPTURE_TIMEOUT_SECONDS=20
STORAGE_BACKEND=csv
CSV_PATH=logs/chill_predictions.csv
GOOGLE_SHEETS_SPREADSHEET_ID=...
GOOGLE_SHEETS_WORKSHEET=predictions
GOOGLE_SERVICE_ACCOUNT_JSON='{"type":"service_account",...}'
DRY_RUN=false
LOG_LEVEL=INFO
ALLOW_MISSING_HOURLY_FIELDS=
JMA_FORECAST_ENABLED=false
JMA_OFFICE_CODE=140000
JMA_AREA_CODE=140010
JMA_TIMEOUT_SECONDS=20
WEBHOOK_HOST=127.0.0.1
WEBHOOK_PORT=8080
GITHUB_REPOSITORY=kikurage-en/SunsetChillAPP
GITHUB_WORKFLOW=daily_chill.yml
GITHUB_REF=main
GITHUB_TOKEN=
VISION_ENABLED=false
VISION_API_KEY=
VISION_MODEL=gemini-2.5-flash
VISION_TIMEOUT_SECONDS=30
VISION_TARGET_HOURS=16,17,18,19
SUNSET_CLOUD_OFFSET_KM=40
SUNSET_CLOUD_NEAR_OFFSET_KM=20
SUNSET_VISION_BLEND_WEIGHT=0.8
SUNSETHUE_ENABLED=false
SUNSETHUE_API_KEY=
SUNSETHUE_TIMEOUT_SECONDS=20
```

`JMA_FORECAST_ENABLED=true` では、気象庁の神奈川県東部向け6時間降水確率を取得します。
LINEの降水確率表示とChill指数の降水リスクにはこの値を優先し、取得できない場合だけ
Open-Meteoの対象時間帯最大値へフォールバックします。GitHub Actions本番は有効です。
気象庁値は6時間・予報区単位、Open-Meteo値は地点格子・時間単位で定義が異なるため、
Sunset期待度には後者を維持し、両方をログへ分けて保存します。

`SUNSET_CLOUD_OFFSET_KM` は、Sunset期待度の**遮蔽側の雲**（低層雲・総雲量）をどれだけ西(日没方位)へ離れた地点から取得するかの距離（km）です。既定は 40。`0` を指定すると西地点分離を全て無効化し、Chill指数と同じ逗子海岸の雲量で Sunset期待度を算出します。

`SUNSET_CLOUD_NEAR_OFFSET_KM` は、**発色源の雲**（中・高層雲＝日没後も日照が届く観測者寄りの「キャンバス」）を取得する近距離側の地点（km）です。既定は 20。`0` を指定すると中・高層雲は逗子海岸の値を使います。

`SUNSET_VISION_BLEND_WEIGHT` は、日没前のVisionカメラAI予測を Sunset期待度の表示値へブレンドする際の Vision の重み（0〜1）です。既定は 0.8（Vision 8 割・式 2 割）。`0` を指定するとブレンドを無効化し、式スコアをそのまま表示します。ブレンドは日没前（予測モード）でVision解析が成功した実行にのみ適用され、純式スコア `sunset_score` はログにそのまま残します。17:00 のカメラは「これから西から来る雲の壁」を写せないため、Vision による**上方修正は式スコア+30 までに制限**します（下方修正は無制限。詳細は「スコア計算」節）。

## LINE Messaging API

LINE Developers で Messaging API チャネルを作成し、チャネルアクセストークンを `LINE_CHANNEL_ACCESS_TOKEN` に設定します。送信先のユーザーID、グループID、または複数人チャットIDを `LINE_TARGET_ID` に設定します。

`LIVE_CAMERA_IMAGE_URL` または `LIVE_CAMERA_IMAGE_BASE_URL` が設定されている場合は、LINE本文に続けて画像メッセージも送信します。画像URLはLINEから取得できるHTTPS URLである必要があります。`LIVE_CAMERA_IMAGE_BASE_URL` を使う場合、画像URLは `live-camera/YYYY-MM-DD/HHMM.jpg` として組み立てます。

Webhookでメンション応答を使う場合は、チャネルシークレットを `LINE_CHANNEL_SECRET` に設定します。グループ内の他ユーザーへのメンションで誤反応させないため、可能ならbotのユーザーIDを `LINE_BOT_USER_ID` に設定します。

## ローカル実行

```bash
python -m zushi_chill.main --dry-run
python -m zushi_chill.main --dry-run --date 2026-06-01 --run-time 13:00
python -m zushi_chill.main --dry-run --input-json tests/fixtures/open_meteo_sample.json --date 2026-06-01 --run-time 13:00
python -m zushi_chill.main
```

`--dry-run` または `DRY_RUN=true` では LINE 送信を行わず、投稿文を標準出力に表示し、CSV に `line_sent=false` で保存します。
`--date YYYY-MM-DD` を指定した場合は、Open-Meteo の対象日にも `start_date/end_date` として渡します。
`--input-json` はOpen-Meteo APIと気象庁JSONを呼ばず、保存済みOpen-Meteoレスポンスから算出します。ローカルの再現確認やfixtureを使った検証に使い、この場合のChill指数はOpen-Meteo値へフォールバックします。

Open-Meteo の必須変数に欠損がある場合は異常終了します。一部の欠損を許容したい場合は `ALLOW_MISSING_HOURLY_FIELDS=visibility,wind_gusts_10m` のように指定できます。許容したフィールドでも、評価時間帯の値がすべて欠損している場合は異常終了します。

## エラーハンドリング

Open-Meteo API取得は最大3回リトライし、最終失敗時は異常終了してLINE送信しません。必須変数の欠損、時刻形式不正、評価時間帯のデータ不足、非数値データも異常終了します。気象庁降水確率の取得失敗は非致命で、警告後にOpen-Meteo値を使って継続します。

通常実行では、まず `line_sent=false` の予測ログを保存してからLINE送信します。LINE送信に失敗した場合は、同じ `date`、`run_time`、`location_name` の行に `line_sent=false` と `error_message` を記録し、処理全体は異常終了扱いにします。

保存に失敗した場合、LINE送信前であればLINE送信しません。LINE送信後の保存更新に失敗した場合は、送信済みであることが分かるログを出して異常終了します。

## GitHub Actions

`.github/workflows/daily_chill.yml` は `workflow_dispatch` で実行されます。GitHub UI から手動実行できるほか、Contaboのcronから `zushi-chill-trigger-actions` で起動します。

定期実行では、Contaboのcronが `13:00` / `17:00` を固定の `run_time` として渡します。日没時と**日没+20分**は、Contaboのsystemd timerがローカル計算した日没時刻とSQLiteの永続ジョブに基づいて実行します。予定時刻に一時停止していても既定60分以内なら追いつき撮影し、撮影後のOpen-Meteo・GitHub・Vision・保存失敗は同じ画像で再試行します。日没時はLINEを送らず画像評価と保存だけを行い、日没+20分は残照評価とLINE通知を行います。観測固有の `observation_id` とLINEの再送キーで、再実行時のログ上書きと通知重複防止を行います。13:00 / 17:00など日没前の予測メッセージでは、日没時刻に最も近いOpen-Meteoのhourly行から気温・湿度・風・夕焼け方向の層別雲量・視程を表示します。最寄りhourly時刻は本文へ表示せずログへ保存します。日没時・残照フェーズのコメントは予測表現を使わず、その時点の条件を説明します。気象庁の降水確率は日没を含む6時間値です。対象時間帯、予報体感温度、突風、降水確率の期間・区域・出典は本文へ表示せず、計算・ログでは維持します。

本文冒頭は装飾やサービス名を付けず、`YYYY-MM-DD HH:MM` だけを表示します。
コメントは人手での現地確認を依頼せず、LINE表示用の最終Sunset期待度とChill指数を「良好・中程度・
低調」の3段階で組み合わせた見通しを表示します。補足は低層雲、高い体感温度、強風、
高層雲、降水信号の矛盾から優先度が最も高い1件だけを表示します。通常コメントと
ライブカメラコメントは各文末に「っピ」を付け、高評価では明るく、低評価では静かな
調子に変化させます。13:00 / 17:00 の予測では、日没前後で雨予報が大きく変わる場合、
にわか雨・雷雨、予報値の欠測や予報間の大幅な差、式とライブカメラAI予測の25点以上の
乖離などを検知すると、スコアは変えずに総評だけを弱気で自信なさげな表現へ切り替えます。

13:00 / 17:00と手動実行はGitHub Actionsで、日没連動ジョブは予定時刻に近いContabo側で `LIVE_CAMERA_URL` のYouTubeライブから1フレームを取得します。日没連動画像は45KB以下のJPEGへ正規化してローカルに固定し、Base64形式のworkflow inputとしてSHA-256と一緒にGitHub Actionsへ渡します。Actions側はハッシュを照合してから使用するため、再試行時にも最初に撮影できた同一画像を処理します。全ジョブとも画像を `pages-images` branchへ累積保存し、GitHub Pagesへ `live-camera/YYYY-MM-DD/HHMM.jpg` としてデプロイします。同じパスへ異なる画像を上書きする実行は失敗させ、過去URLと元画像を保持します。ライブストリームURLを解決できない場合は、`LIVE_CAMERA_VIDEO_ID` からYouTubeのライブサムネイルを取得してフォールバックします。取得に成功した場合のみ、そのPages URLをLINE画像メッセージとして添付します。GitHub Pagesはリポジトリ設定でSourceを「GitHub Actions」にしておきます。Pages URLが標準の `https://<owner>.github.io/<repo>` と異なる場合は、Secret `LIVE_CAMERA_IMAGE_BASE_URL` で上書きします。

画像の長期保存元は `pages-images` branchです。加えて、各実行のArtifactを90日保持します。Artifact名は `live-camera-YYYY-MM-DD-HHMM` です。GitHub Actionsの実行画面から取得するか、GitHub CLIを使う場合は `gh run download <RUN_ID> -n live-camera-YYYY-MM-DD-HHMM` でダウンロードできます。Pagesを履歴branchから再構築する場合は `Publish image history` workflowを手動実行します。保存画像を別モデルで一括再採点する専用CLIは現時点では未実装です。

手動実行では `manual_mode`、`date`、`run_time` を指定できます。`manual_mode=dry_run` では通常通知・失敗通知のどちらもLINE送信せず保存処理まで確認し、`manual_mode=send_line` ではLINE送信と送信後の保存更新まで確認します。`date` は `YYYY-MM-DD`、`run_time` は `HH:MM` 形式です。

`STORAGE_BACKEND=csv` の場合、CSV は `CSV_PATH`（未指定時は `logs/chill_predictions.csv`）に保存され、Actions Artifact としてアップロードされます。`STORAGE_BACKEND=google_sheets` の場合は Google Sheets へ保存し、CSV Artifact は作成しません。

## Contabo + GitHub Actions運用

独自ドメインがない場合、定期実行はContaboのcronからGitHub Actionsを起動し、キャプチャ画像のHTTPS公開とLINE送信はGitHub Actions/GitHub Pages側で行います。この構成ではContaboに公開HTTPSエンドポイントを持たせないため、ドメインなしで定期投稿を運用できます。

Contabo側にはPython 3.12とこのリポジトリを配置し、GitHub Personal Access Tokenを `GITHUB_TOKEN` に設定します。Tokenには対象リポジトリのActions workflow dispatchと実行結果を読む権限が必要です。観測画像をworkflow inputで渡すため、Contentsの書き込み権限は不要です。

```txt
GITHUB_REPOSITORY=kikurage-en/SunsetChillAPP
GITHUB_WORKFLOW=daily_chill.yml
GITHUB_REF=main
GITHUB_TOKEN=...
```

13:00 / 17:00は従来どおりContaboのcronから起動します。日没時と日没+20分は永続観測スケジューラが起動し、日没時だけ `manual_mode=dry_run`、日没+20分は `manual_mode=send_line` です。

```bash
# 13:00 / 17:00 は固定時刻で予測を通知
zushi-chill-trigger-actions --date "$(TZ=Asia/Tokyo date +%F)" --run-time 13:00
zushi-chill-trigger-actions --date "$(TZ=Asia/Tokyo date +%F)" --run-time 17:00

# 日没連動ジョブを手動で1回確認する
zushi-chill-observation-scheduler
```

初回だけ依存関係とsystemd unitをインストールします。これにより毎分のジョブ処理と21:30 JSTの完全性監査が有効になります。`ffmpeg` がない場合もYouTubeサムネイルへフォールバックしますが、正確な時刻の動画フレームを優先するため本番ではインストールします。`scripts/schedule_sunset_capture.sh` は旧8時cronが一時的に残っていても同じ永続スケジューラを1回呼ぶ互換ラッパーで、`at` は使いません。

```bash
cd /opt/SunsetChillAPP
git pull --ff-only
.venv/bin/pip install --upgrade -e . yt-dlp
sudo apt-get update
sudo apt-get install -y ffmpeg
sudo /opt/SunsetChillAPP/scripts/install_observation_scheduler.sh
systemctl list-timers 'zushi-chill-observation-*'
```

```cron
0 13 * * * cd /opt/SunsetChillAPP && /opt/SunsetChillAPP/.venv/bin/zushi-chill-trigger-actions --run-time 13:00 --manual-mode send_line >> /var/log/zushi-chill-actions-trigger.log 2>&1
0 17 * * * cd /opt/SunsetChillAPP && /opt/SunsetChillAPP/.venv/bin/zushi-chill-trigger-actions --run-time 17:00 --manual-mode send_line >> /var/log/zushi-chill-actions-trigger.log 2>&1
```

```bash
# 当日の未完了ジョブを確認（空配列・終了コード0が正常）
zushi-chill-observation-scheduler --audit

# 状態と再試行ログを確認
journalctl -u zushi-chill-observation-scheduler.service
```

永続状態は既定で `/var/lib/zushi-chill/observation_jobs.sqlite3`、撮影画像は
`/var/lib/zushi-chill/spool` に置きます。`AFTERGLOW_OFFSET_MINUTES`（既定20）、
`OBSERVATION_CAPTURE_MAX_DELAY_MINUTES`（既定60）などは `.env` で変更できます。
workflow dispatch全体の入力上限に収めるため、日没連動画像は最大45KBです。これを超える画像は
ffmpegで段階的に縮小・再圧縮し、正規化できない場合は送信せず同じジョブとして再試行します。
撮影前にサーバーまたはカメラが60分を超えて停止した場合、過去時点の画像は復元できないため
ジョブを `capture_missed` として監査に残します。撮影後の処理は時間制限なく再試行しますが、
LINEの重複防止キーは24時間保持のため、23時間以降は古い通知を再送せずログ回復だけを行います。

実行前にpayloadだけ確認する場合は `--dry-run` を付けます。

```bash
zushi-chill-trigger-actions --dry-run --run-time 13:00
```

LINEメンション応答には、LINE Developersに登録できる公開HTTPS Webhook URLが必要です。独自ドメインなしのContabo単体ではこの入口を安定運用できないため、メンション応答を有効化する場合は、ドメインを取得してNginx/Let's Encryptで `https://<domain>/line/webhook` を公開するか、固定HTTPS URLを提供するトンネル/外部Webhook基盤を別途用意します。

## Google Sheets 連携

CSV の代わりに Google Sheets へ保存する場合は、対象スプレッドシートをサービスアカウントのメールアドレスに共有し、以下を設定します。

```txt
STORAGE_BACKEND=google_sheets
GOOGLE_SHEETS_SPREADSHEET_ID=...
GOOGLE_SHEETS_WORKSHEET=predictions
GOOGLE_SERVICE_ACCOUNT_JSON='{"type":"service_account",...}'
```

指定ワークシートがない場合は自動作成します。ワークシートの1行目には保存カラムのヘッダーが自動で作られます。同じ `date`、`run_time`、`location_name` の行がある場合は、LINE送信結果を同じ行へ更新します。

## ライブカメラ画像の Vision 解析

`VISION_ENABLED=true` かつ `VISION_API_KEY` が設定されている場合、`VISION_TARGET_HOURS`（カンマ区切り、既定 `16,17,18,19`。旧 `VISION_TARGET_HOUR` も単一時刻として後方互換）に含まれる時刻の実行でのみ、保存済みのライブカメラ画像を Vision LLM（既定 `gemini-2.5-flash`）で解析します。日没時ジョブを予約しても、この2設定がなければ画像の保存だけでVision評価値は記録されません。解析は3フェーズです。日没前は雲の構造から今夜の夕焼けを**予測**、日没時〜+10分は**太陽ディスクの見えやすさ**と**日没時の発色**を別々に評価、+10分より後は**残照**を評価します。解析結果はLINE本文とログ（`vision_*` カラム）に記録します。画像はローカル保存ファイルを優先して送信し、無い場合のみ公開URLをダウンロードして送信します。解析が失敗してもメインのスコア算出・LINE送信・保存は継続します。

日没前（予測フェーズ）のVisionカメラAI予測は、`Sunset期待度` の**表示値**へブレンドされます（`SUNSET_VISION_BLEND_WEIGHT`、既定 Vision 8 割）。ただし式単体の精度を前向きに検証し続けられるよう、**純式スコア `sunset_score` はログにそのまま残し**、ブレンド値は別カラム `final_sunset_score` に記録します（詳細は「スコア計算」節）。日没時・残照フェーズは予測へのブレンドに使わず、観測画像の代理指標として記録します。`Chill指数` は Vision の影響を受けません。

従来の `vision_sunset_score` / `vision_sky_condition` / `vision_comment` / `vision_model` に加え、`vision_evaluation_phase` / `vision_sun_disk_visibility` / `vision_sunset_color_score` / `vision_afterglow_score` を記録します。`vision_sunset_score` は後方互換の総合値として残します。同じAIによる画像採点は独立した真値ではなく**画像代理指標**ですが、元画像をArtifactに保存するため、将来モデルや評価基準を変えて再採点できます。

保存スキーマは74列です。従来の68列へ、`observation_id`、`observation_phase`、`scheduled_at`、`captured_at`、`capture_delay_seconds`、`observation_data_quality` を末尾追加し、予定時刻と実撮影時刻を混同せず遅延データを識別できるようにしています。既存のCSVを使う場合はこの6列をヘッダーへ追加してください（不一致時は `ConfigError` で停止）。Google Sheetsは列幅を74列まで自動拡張し、prefixが一致する旧ヘッダーを自動移行します。

## Sunsethue API による独立ベンチマーク（log-only）

`SUNSETHUE_ENABLED=true` かつ `SUNSETHUE_API_KEY` が設定されている場合、各実行で [Sunsethue API](https://sunsethue.com/dev-api)（`GET https://api.sunsethue.com/event`）から逗子海岸の夕焼け品質予測を取得し、ログに記録します。Sunsethue は「日没時に光が雲へ届くか」を計算する ray-model で、西の水平線の抜けと上空の雲を内部で評価するため、座標は逗子海岸をそのまま渡します（`SUNSET_CLOUD_OFFSET_KM` の西地点分離は不要）。

これは**式・Vision とは独立したベンチマーク**であり、**Chill 指数・Sunset 期待度・`final_sunset_score` のいずれも変えません**。目的は「式 `sunset_score` / Visionカメラ予測 / Sunsethue」を、日没時の発色と+20分の残照という画像代理指標に対して前向きに比較することです。取得に失敗してもメインのスコア算出・LINE送信・保存は継続します（非致命）。

ログには `sunsethue_quality`（0〜100、Sunsethue の `quality` 0〜1 を 100 倍）/ `sunsethue_cloud_cover`（%、`cloud_cover` 0〜1 を 100 倍）/ `sunsethue_quality_text`（Poor/Fair/Good/Great）の 3 カラムが追加されます（Google Sheets は自動移行）。認証は API キーを `key` クエリパラメータで渡します。Sunsethue は Cloudflare 配下でブラウザ以外の User-Agent を拒否するため、クライアントはブラウザ相当の User-Agent を送ります。無料枠は 1000 credits/日・**非商用**です。

## 前向き検証運用

1. 13:00 JST に昼時点の見込みを確認
2. 17:00 JST に夕方直前の見込みを確認（Vision「ライブカメラAI予測」も記録）
3. 日没時にカメラ画像を保存し、太陽ディスクの見えやすさと日没時の発色を自動記録する（LINE送信なし）
4. 日没+20分に画像を保存して残照を自動記録し、LINEにも残照評価を送信する
5. 蓄積後に、17:00の各予測と同一日の `vision_sunset_color_score` / `vision_afterglow_score` の乖離を別々に確認する

式の乖離検証には、表示用のブレンド値 `final_sunset_score` ではなく**純式スコア `sunset_score`**（17:00行）を使います。同一 `date` の日没時行にある `vision_sunset_color_score` と、+20分行の `vision_afterglow_score` に対する誤差を別集計し、どちらの目的を改善した変更かを明示します。`vision_sun_disk_visibility` は遮蔽判定の診断指標として使います。乖離が大きい日は保存画像を再確認・再採点できます。

高い降水確率と雨量0が食い違う日は、集計窓の最大値・合計値だけでなく、日没を挟む2つの時間値を使います。例えば日没18:54なら18:00を `before_sunset`、19:00を `at_sunset` とし、各時点の降水確率・雨量・天気コード・視程を保存します。これらは現時点では診断専用で、スコアを直接変えません。なおOpen-Meteoの降水確率・降水量・突風はタイムスタンプまでの直前1時間値なので、対象時間帯の集計だけはその区間終端として1時間補正します。

## スコア計算

`Sunset期待度` は 100 点から低層雲、Open-Meteoの対象時間帯降水確率、視程、強風のペナルティを引き、中層雲と高層雲の条件が良い場合にボーナスを加えます。気象庁の降水確率は「6時間・神奈川県東部で1mm以上」、Open-Meteoは「時間単位・地点格子で0.1mm超」と定義が異なります。夕焼けイベントの時刻と地点へ近い後者をSunset式に維持し、前者は式へ混ぜません。ただしペナルティが1つでもある場合は上限 95、降水確率 20%以上では上限 90 に制限し、ボーナスでペナルティを相殺して満点に戻ることを防ぎます。総雲量 70%以上では上限 65、85%以上では上限 30、低層雲と中層雲がどちらも70%以上では上限30、視程 5,000m 未満では上限 50 に制限します。厚い中層雲は低い夕日を遮るため、中層雲 55%以上では上限 60、70%以上では上限 40 に制限します。評価時間帯の代表天気コードが雨・雷雨系、または窓内の予想雨量合計が 1.0mm 以上の場合（雨シグナル。Chill式と同じ判定軸）は上限 40 に制限します。減点の深さを予想雨量に比例させない根拠と覆り条件は `STATUS.md` の「2026-07-25 乖離検証」を参照してください。さらに、指標分離前の+20分Vision総合評価で85点以上が稀（35日中1日）だった履歴に基づき、好条件でも通常の上限は80とし、色を最大限に通す超快晴（総雲量15%未満かつ低層雲5%未満）のみ90まで許します。この旧Vision値は独立した真値ではなく、過去の画像代理指標です。

降水確率80%以上の通常ペナルティは-60です。ただし、評価時間帯の予想雨量が0、代表天気コードが0/1、西側総雲量が50%未満、西側低層雲が30%未満をすべて満たす場合だけ、矛盾信号として暫定的に-25へ緩和します。「雨なし」と断定する条件ではなく、LINEにも予測の不確実性が高い旨を表示します。湿度は霞の代理としてSunset期待度へ直接減点せず、Chill指数と保存済みの視程で扱います。

夕焼けの見え方は「陽が沈む方角（西の水平線）の雲」に支配されるため、`Sunset期待度` の雲量は逗子海岸ではなく、当日の日没方位の地点から**雲の高さごとに距離を変えて**取得します。遮蔽側の低層雲・総雲量は `SUNSET_CLOUD_OFFSET_KM`（既定40km、光路上のブロッカー）、発色源の中・高層雲は `SUNSET_CLOUD_NEAR_OFFSET_KM`（既定20km、日没後も日照が届く観測者寄りのキャンバス）の地点の値を使います。日没方位は季節で変動する（逗子で夏至≈299°、冬至≈241°）ため、日付から都度計算します。遠地点の取得に失敗した場合は逗子海岸の雲量へ、近地点の取得に失敗した場合は遠地点の値へフォールバックします。ログには使用した雲量を `sunset_cloud_cover` / `sunset_cloud_cover_low`（遠地点）/ `sunset_cloud_cover_mid` / `sunset_cloud_cover_high`（近地点）として記録します。

式（`sunset_score`）は単一時刻の雲スカラー値だけを使うため、「雲が光を遮る日」と「雲が夕日を受けて赤くなる日」を分離できません。実際の空を見るVisionカメラAI予測の方が精度が高いため、日没前（予測モード）でVision解析が成功した実行では、LINE本文に表示する `Sunset期待度` を式スコアとVision予測スコアのブレンドで算出します。

```txt
final_sunset_score = round(
    (1 - SUNSET_VISION_BLEND_WEIGHT) * sunset_score
    + SUNSET_VISION_BLEND_WEIGHT * vision_sunset_score
)
```

`SUNSET_VISION_BLEND_WEIGHT`（既定 0.8）が 0、Vision が無効・欠測、または日没時・残照フェーズの実行では、ブレンドせず `final_sunset_score = sunset_score` とします。またブレンド結果には**上方キャップ `final_sunset_score ≤ sunset_score + 30`** を適用します。17:00 のカメラは逗子上空の見かけしか写せず「これから西から来る雲の壁」（式が西地点の予報で捕捉するもの）を見えないため、Vision の楽観による持ち上げ幅を制限します。加えて雨シグナル（前節の判定）の実行では上方修正そのものを無効化し、`final_sunset_score ≤ sunset_score` とします（2026-07-25: 窓内4.7mm・雨コードの予報下でVision 65が表示を45→61へ持ち上げ、実際の日没時発色は0だった）。下方修正は制限しません（目の前の悪い空を写しているカメラは信頼できるため）。**純式スコア `sunset_score` はブレンドで上書きせず別カラムで保持**し、同一日の `vision_sunset_color_score` と `vision_afterglow_score` に対する誤差を別々に検証します。表示ラベル（S〜D）は `final_sunset_score` を基準にします。

`Chill指数` は対象時間帯平均の体感温度、湿度、風、降水リスク、Sunset期待度（純式 `sunset_score`）を重み付きで合成します。Vision ブレンドの影響は受けません。降水リスクは一般の天気予報と認識を揃えるため気象庁の6時間降水確率を優先し、欠測時だけOpen-Meteoへフォールバックします。日没前のLINE予測には日没時刻に最も近いhourly気温・湿度・風などを表示しますが、Chill計算用の体感温度・湿度・風は対象時間帯集計のまま分離します。Chill指数の雲量など他の気象値は逗子海岸のOpen-Meteo値です。降水確率、降水量、平均風速、突風、雨・雷雨系の天気コード、肌寒く感じやすい体感温度、雲が厚く滞在感が重くなりやすい条件に応じて上限を制限します。

`Sunset期待度` の初期式は以下です。

```txt
100
- 低層雲ペナルティ
- 降水ペナルティ
- 視程ペナルティ
- 強風ペナルティ
+ 中層雲ボーナス
+ 高層雲ボーナス
総雲量が多い場合は上限を制限
```

`Chill指数` の初期式は以下です。

```txt
体感温度スコア * 0.30
+ 湿度スコア * 0.20
+ 風スコア * 0.20
+ 降水リスクスコア * 0.20
+ Sunset期待度 * 0.10
体感温度が22℃未満の場合は上限を制限
総雲量が多い場合は上限を制限
```

強制上限は、降水確率70%以上でChill指数40、降水量1.0mm以上で45、平均風速8m/s以上で55、最大突風12m/s以上で50、雨・雷雨系の天気コードで45、体感温度20〜21.9℃で80、18〜19.9℃で70、18℃未満で55、総雲量70〜84%で69、85%以上で65、低層雲と中層雲がどちらも70%以上で65です。Sunset期待度は、総雲量70〜84%で65、85%以上で30、低層雲と中層雲がどちらも70%以上で30、中層雲55〜69%で60、70%以上で40、雨・雷雨系の天気コードまたは窓内予想雨量1.0mm以上で40、視程5,000m未満で50に制限し、天井は通常80（総雲量15%未満かつ低層雲5%未満の超快晴のみ90）です。総合判定ラベルは `S=85〜100`、`A=70〜84`、`B=55〜69`、`C=40〜54`、`D=0〜39` です。

### 高降水確率・雨量0型の暫定補正（2026-07-21）

2026-07-21は、集計降水確率87%による-60だけで純式40になりましたが、予想雨量0、天気コード0、西側総雲量17%、低層雲10%で、画像代理値は日没時の発色・+20分の残照とも80でした。17:00のVision予測68、表示値62に対し、上記の限定補正なら純式75・表示値69となります。

ただし、同型の履歴は2026-06-12と2026-07-21の**N=2のみ**です。旧画像代理値を含む比較可能な13件では、暫定補正により純式のMAEは14.9から12.2へ改善する一方、biasは+2.8から+5.5へ楽観側に広がります。また2026-07-16は降水確率75%・雨量0でも天気コード2で、純式60に対して旧画像代理値25でした。この反例へ緩和を広げないため、80%以上・コード0/1・西空の薄い雲という条件を固定しています。

日没時の発色と残照を分離した新しい画像代理値自体も2026-07-20、21の2日分しかありません。この補正は最終校正ではなく、同型が10件以上になるまで暫定扱いとします。再評価時は末尾8つの `*_before_sunset` / `*_at_sunset` 列、17:00の各予測、日没時の発色、+20分の残照、保存画像を同日単位で突合します。補正後の純式が画像代理値を20点以上上回る例が3件に達した場合は、10件を待たずに条件を見直します。

### 気象庁降水確率とSunset式の使い分け（2026-07-21）

既存ログの17:00予測と同日の画像代理値を突合できた40件では、保存済みのOpen-Meteo
降水確率（直前1時間値の区間補正前）と画像代理値の相関は `-0.287` でした。最新式の
MAEは17.6、降水確率の減点を外した場合は
18.2で、弱いながら識別力を残しています。またOpen-Meteoが80%以上だった9件中4件は
画像代理値50以上で、降水確率単独を強い遮蔽判定にできないことも確認しました。このため
Sunset式ではOpen-Meteoを暫定維持し、雨量・天気コード・西空との矛盾補正を併用します。

既存ログには当時発表された気象庁値が保存されておらず、気象庁値で同じMAEを遡及計算
することはできません。2026-07-21の17時発表では神奈川県東部18〜24時が20%で、同日の
Open-Meteoログ87%、日没時発色・残照80とは大きく異なりましたが、1件だけで優劣は
決めません。過去の全hourly値は保存していないため区間補正後の値も遡及再計算できません。
以後は補正済みOpen-Meteo値と `jma_precipitation_*` 5列を同時保存し、比較可能なN≥10で
画像代理値に対するMAE・bias・順位相関を再評価します。

## テストと品質確認

```bash
ruff check .
pytest
```

スコア計算、ラベル境界、強制上限、メッセージ生成、Open-Meteoレスポンス解析、気象庁6時間降水確率の期間選択、APIリトライ、dry-run CLI、CSV・Google Sheets保存、Visionの3フェーズと個別評価値、日没連動スケジューラ、GitHub Actionsの画像Artifact契約をテストしています。SNS投稿、画像生成、自動最適化はMVPに含めていません。

## 今後の改善

- 保存画像を対象にした一括再採点CLI
- 画像代理指標の蓄積に基づくスコア重み調整
- 高降水確率・雨量0型を同型N≥10で再評価（末尾8つの日没前後診断列を使用）
- 気象庁値とOpen-Meteo値を同時にN≥10蓄積後、Sunset画像代理値への識別力を比較
- 必要な場合のみ、日没30分前の短時間予報・直達日射量を追加信号として検証
- SNS向け短文や画像生成の検討
- 複数地点対応の検討
