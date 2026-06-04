# 逗子サンセットチル指数 MVP 要件定義書

## 1. プロジェクト概要

### 1.1 目的

逗子海岸の海の家スタッフ向けに、毎日夕方の「Sunset期待度」と「Chill指数」を自動算出し、LINEグループへ投稿するMVPを実装する。

2026年6月中はSNS投稿には使用せず、スタッフが実際の空模様・夕焼け・体感快適度を目視で検証する。
6月末に予測指数と実測評価の乖離を分析し、計算式を調整したうえで、7月以降にSNS運用へ展開するか判断する。

### 1.2 MVPの位置づけ

本MVPは、一般利用者向けの気象予報サービスではなく、店舗内部での検証用ツールとする。

外部向け表現では「予報」という言葉の利用は避け、正式運用時も原則として「逗子サンセットチル指数」「夕方の来店参考指数」「Sunset期待度」などの表現を使用する。

### 1.3 対象地点

* 対象エリア：逗子海岸周辺
* 緯度経度：環境変数で指定可能にする
* 初期値例：

  * `LOCATION_NAME=逗子海岸`
  * `LATITUDE=35.2956`
  * `LONGITUDE=139.5736`
* タイムゾーン：`Asia/Tokyo`

### 1.4 検証期間

* 初期検証期間：2026年6月1日〜2026年6月30日
* 通知頻度：1日2回

  * 13:00 JST：昼時点の見込み
  * 17:00 JST：夕方直前の見込み
* 追加で手動実行できるようにする

---

## 2. 実装対象

### 2.1 MVPで実装するもの

* Open-Meteo APIから逗子海岸周辺の気象データを取得
* 当日の日没時刻を取得
* 日没前後の時間帯を抽出
* Sunset期待度を算出
* Chill指数を算出
* スタッフ向けコメントを生成
* LINE Messaging APIでスタッフLINEグループへテキスト投稿
* 算出結果をGoogle SheetsまたはCSVに保存
* GitHub Actionsで毎日自動実行
* 手動実行用の `workflow_dispatch` を用意
* pytestによる主要ロジックのテストを実装

### 2.2 MVPで実装しないもの

* SNS用画像生成
* Instagram / X / TikTok等への自動投稿
* 管理画面
* ユーザー向けWebページ
* 機械学習によるスコア最適化
* Webカメラ画像解析
* 一般公開向けの気象予報サービス
* 複数地点対応
* 課金・認証機能

---

## 3. 利用技術

### 3.1 推奨構成

* 言語：Python 3.12
* 実行環境：GitHub Actions
* 気象API：Open-Meteo Forecast API
* 通知：LINE Messaging API
* 記録：

  * 第1候補：Google Sheets
  * 第2候補：CSVをGitHub Actions Artifactとして保存
* テスト：pytest
* Lint / Format：ruff
* 設定管理：`.env` または GitHub Secrets

### 3.2 推奨ディレクトリ構成

```txt
.
├── README.md
├── REQUIREMENTS.md
├── pyproject.toml
├── .env.example
├── src
│   └── zushi_chill
│       ├── __init__.py
│       ├── config.py
│       ├── weather_client.py
│       ├── scoring.py
│       ├── message_builder.py
│       ├── line_client.py
│       ├── storage.py
│       └── main.py
├── tests
│   ├── test_scoring.py
│   ├── test_message_builder.py
│   └── fixtures
│       └── open_meteo_sample.json
└── .github
    └── workflows
        └── daily_chill.yml
```

---

## 4. 外部API要件

## 4.1 Open-Meteo API

### 4.1.1 エンドポイント

```txt
https://api.open-meteo.com/v1/forecast
```

### 4.1.2 必須パラメータ

```txt
latitude={LATITUDE}
longitude={LONGITUDE}
timezone=Asia/Tokyo
forecast_days=1
wind_speed_unit=ms
hourly=temperature_2m,relative_humidity_2m,apparent_temperature,precipitation_probability,precipitation,weather_code,cloud_cover,cloud_cover_low,cloud_cover_mid,cloud_cover_high,visibility,wind_speed_10m,wind_direction_10m,wind_gusts_10m
daily=sunset
```

### 4.1.3 取得する主な変数

| 変数                          | 用途                |
| --------------------------- | ----------------- |
| `temperature_2m`            | 気温表示・ログ           |
| `relative_humidity_2m`      | Chill指数           |
| `apparent_temperature`      | Chill指数           |
| `precipitation_probability` | Sunset期待度・Chill指数 |
| `precipitation`             | 雨判定               |
| `weather_code`              | 荒天・雨天判定           |
| `cloud_cover`               | 参考値               |
| `cloud_cover_low`           | Sunset期待度の主要変数    |
| `cloud_cover_mid`           | Sunset期待度の補正      |
| `cloud_cover_high`          | Sunset期待度の補正      |
| `visibility`                | Sunset期待度の補正      |
| `wind_speed_10m`            | Chill指数           |
| `wind_direction_10m`        | LINE表示            |
| `wind_gusts_10m`            | 強風判定              |
| `daily.sunset`              | 評価対象時間帯の算出        |

### 4.1.4 評価対象時間帯

日没時刻を中心に、以下の時間帯を対象とする。

```txt
日没90分前 〜 日没30分後
```

ただしOpen-Meteoのhourlyデータは基本的に1時間単位であるため、対象時間帯に含まれる時間別データを抽出し、平均値または最大値を算出する。

### 4.1.5 集計方針

| 指標   | 集計方法            |
| ---- | --------------- |
| 気温   | 平均              |
| 体感温度 | 平均              |
| 湿度   | 平均              |
| 降水確率 | 最大              |
| 降水量  | 合計              |
| 低層雲量 | 平均              |
| 中層雲量 | 平均              |
| 高層雲量 | 平均              |
| 視程   | 最小              |
| 風速   | 平均              |
| 突風   | 最大              |
| 風向   | 評価時間帯の中央値または代表値 |

---

## 5. スコア算出要件

## 5.1 出力する指数

### 5.1.1 Sunset期待度

夕陽・夕焼けが見えやすそうかを表す内部検証用スコア。

* 範囲：0〜100
* 高いほど夕陽・夕焼けが期待できる
* 主に低層雲、降水、視程、強風、高層雲を評価する

### 5.1.2 Chill指数

海辺で夕方を過ごしやすそうかを表す内部検証用スコア。

* 範囲：0〜100
* 高いほど海の家での滞在に向く
* 主に体感温度、湿度、風、降水リスク、Sunset期待度を評価する

### 5.1.3 総合判定ラベル

|    スコア | ラベル | 意味      |
| -----: | --- | ------- |
| 85〜100 | S   | かなり良い   |
|  70〜84 | A   | 良い      |
|  55〜69 | B   | 条件つきで良い |
|  40〜54 | C   | やや微妙    |
|   0〜39 | D   | あまり向かない |

---

## 5.2 強制減点・Miss Chill判定

以下の条件に該当する場合、Chill指数の上限を制限する。

| 条件                    | 処理            |
| --------------------- | ------------- |
| 降水確率が70%以上            | Chill指数上限40   |
| 評価時間帯の降水量が1.0mm以上     | Chill指数上限45   |
| 平均風速が8m/s以上           | Chill指数上限55   |
| 最大突風が12m/s以上          | Chill指数上限50   |
| 体感温度が20〜21.9℃          | Chill指数上限80   |
| 体感温度が18〜19.9℃          | Chill指数上限70   |
| 体感温度が18℃未満            | Chill指数上限55   |
| 総雲量が70〜84%             | Sunset期待度上限65 / Chill指数上限69 |
| 総雲量が85%以上              | Sunset期待度上限45 / Chill指数上限65 |
| 低層雲と中層雲がどちらも70%以上   | Sunset期待度上限45 / Chill指数上限65 |
| 視程が5,000m未満           | Sunset期待度上限50 |
| weather_codeが明確な雨・雷雨系 | Chill指数上限45   |

---

## 5.3 Sunset期待度 初期計算式

### 5.3.1 基本式

```txt
Sunset期待度 =
100
- 低層雲ペナルティ
- 降水ペナルティ
- 視程ペナルティ
- 強風ペナルティ
+ 中層雲ボーナス
+ 高層雲ボーナス
総雲量が多い場合は上限を制限
```

最終値は0〜100に丸める。

### 5.3.2 低層雲ペナルティ

|    低層雲量 | ペナルティ |
| ------: | ----: |
|   0〜29% |     0 |
|  30〜49% |   -10 |
|  50〜69% |   -20 |
|  70〜84% |   -35 |
| 85〜100% |   -50 |

### 5.3.3 降水ペナルティ

|    降水確率 | ペナルティ |
| ------: | ----: |
|   0〜19% |     0 |
|  20〜39% |   -10 |
|  40〜59% |   -25 |
|  60〜79% |   -40 |
| 80〜100% |   -60 |

### 5.3.4 視程ペナルティ

|           最小視程 | ペナルティ |
| -------------: | ----: |
|      15,000m以上 |     0 |
| 10,000〜14,999m |    -5 |
|   5,000〜9,999m |   -15 |
|       5,000m未満 |   -30 |

### 5.3.5 強風ペナルティ

|       平均風速 | ペナルティ |
| ---------: | ----: |
|   0〜5.9m/s |     0 |
| 6.0〜7.9m/s |    -5 |
|   8.0m/s以上 |   -10 |

### 5.3.6 中層雲ボーナス

|   中層雲量 | ボーナス |
| -----: | ---: |
| 20〜60% |   +5 |
|    その他 |    0 |

### 5.3.7 高層雲ボーナス

|   高層雲量 | ボーナス |
| -----: | ---: |
| 20〜70% |  +10 |
|    その他 |    0 |

### 5.3.8 雲量上限

|                 条件 | Sunset期待度上限 |
| -----------------: | ----------: |
|          総雲量70〜84% |          65 |
|         総雲量85〜100% |          45 |
| 低層雲と中層雲がどちらも70%以上 |          45 |

---

## 5.4 Chill指数 初期計算式

### 5.4.1 基本式

```txt
Chill指数 =
体感温度スコア * 0.30
+ 湿度スコア * 0.20
+ 風スコア * 0.20
+ 降水リスクスコア * 0.20
+ Sunset期待度 * 0.10
```

最終値は0〜100に丸める。

### 5.4.2 体感温度スコア

|                体感温度 | スコア |
| ------------------: | --: |
|              22〜28℃ | 100 |
|          28.1〜30℃ |  80 |
|           20〜21.9℃ |  70 |
|          30.1〜32℃ |  60 |
|           18〜19.9℃ |  45 |
|          32.1〜34℃ |  40 |
|           16〜17.9℃ |  25 |
|        16℃未満 / 34℃超 |  20 |

### 5.4.3 湿度スコア

|              湿度 | スコア |
| --------------: | --: |
|          55〜75% | 100 |
| 45〜54% / 76〜82% |  80 |
| 35〜44% / 83〜88% |  60 |
|           89%以上 |  40 |
|           35%未満 |  50 |

### 5.4.4 風スコア

|                    平均風速 | スコア |
| ----------------------: | --: |
|              2.0〜5.0m/s | 100 |
| 0.5〜1.9m/s / 5.1〜6.9m/s |  80 |
|              7.0〜8.9m/s |  50 |
|                9.0m/s以上 |  25 |
|                0.5m/s未満 |  60 |

### 5.4.5 降水リスクスコア

|   降水確率 | スコア |
| -----: | --: |
|  0〜19% | 100 |
| 20〜34% |  80 |
| 35〜49% |  60 |
| 50〜69% |  35 |
|  70%以上 |  10 |

---

## 6. LINE通知要件

## 6.1 通知手段

LINE Messaging APIのPush messageを使用する。

### 6.1.1 必要な環境変数

```txt
LINE_CHANNEL_ACCESS_TOKEN=
LINE_TARGET_ID=
```

`LINE_TARGET_ID` には、送信対象のユーザーID、グループID、または複数人チャットIDを設定する。

### 6.1.2 投稿タイミング

| 実行時刻      | 用途       |
| --------- | -------- |
| 13:00 JST | 昼時点の見込み  |
| 17:00 JST | 夕方直前の見込み |

GitHub ActionsではUTCで指定する。

GitHub Actionsのscheduleイベントは遅延またはドロップされる場合があるため、各通知時刻に3回の起動機会を設ける。LINE本文とログの `run_time` は 13:00 / 17:00 として扱い、同じ日付・時刻・地点で `line_sent=true` の記録がある場合は重複送信しない。

| 表示時刻 | Actions実行時刻 |
| ---- | ----------- |
| 13:00 | 04:07 / 04:22 / 04:37 UTC |
| 17:00 | 08:07 / 08:22 / 08:37 UTC |

### 6.1.3 LINE投稿フォーマット

```txt
【逗子サンセットチル指数｜{date} {run_time}時点】

Chill指数：{chill_score} / 100（{chill_label}）
Sunset期待度：{sunset_score} / 100（{sunset_label}）

日没：{sunset_time}
体感温度：{apparent_temperature}℃
湿度：{humidity}%
風：{wind_direction_label} {wind_speed}m/s
突風：{wind_gusts}m/s
降水確率：{precipitation_probability}%
低層雲：{cloud_low}%
中層雲：{cloud_mid}%
高層雲：{cloud_high}%
視程：{visibility_km}km

コメント：
{comment}

検証メモ：
実際の空模様と快適度を「◎ / ○ / △ / ×」で記録してください。
Googleフォーム：
{GOOGLE_FORM_URL}
```

### 6.1.4 コメント生成ルール

LLMは使わず、ルールベースでコメントを生成する。

例：

| 条件                         | コメント                                      |
| -------------------------- | ----------------------------------------- |
| Chill指数80以上かつSunset期待度70以上 | 夕方の滞在環境、夕陽ともに期待できそうです。実際の空の抜け感を確認してください。  |
| Chill指数70以上かつSunset期待度50未満 | 体感は良さそうですが、低層雲や降水リスクの影響で夕陽は控えめかもしれません。    |
| Chill指数50未満                | 風・湿度・雨リスクのいずれかがネックです。実際の滞在感を重点的に確認してください。 |
| 低層雲70%以上                   | 低層雲が多く、夕陽が隠れる可能性があります。                    |
| 高層雲20〜70%かつ低層雲50%未満        | 高層雲がほどよく、夕焼け色が出る可能性があります。                 |
| 風速8m/s以上                   | 風が強めです。海辺での体感は指数より厳しく感じる可能性があります。         |

---

## 7. ログ保存要件

## 7.1 保存先

初期実装では以下のどちらかを選べるようにする。

1. Google Sheets
2. ローカルCSV

環境変数 `STORAGE_BACKEND` で切り替える。

```txt
STORAGE_BACKEND=google_sheets
```

または

```txt
STORAGE_BACKEND=csv
```

## 7.2 予測ログの保存カラム

| カラム                         | 内容        |
| --------------------------- | --------- |
| `date`                      | 対象日       |
| `run_time`                  | 実行時刻      |
| `location_name`             | 地点名       |
| `latitude`                  | 緯度        |
| `longitude`                 | 経度        |
| `sunset_time`               | 日没時刻      |
| `target_window_start`       | 評価開始時刻    |
| `target_window_end`         | 評価終了時刻    |
| `chill_score`               | Chill指数   |
| `chill_label`               | Chill判定   |
| `sunset_score`              | Sunset期待度 |
| `sunset_label`              | Sunset判定  |
| `temperature_2m`            | 平均気温      |
| `apparent_temperature`      | 平均体感温度    |
| `relative_humidity_2m`      | 平均湿度      |
| `precipitation_probability` | 最大降水確率    |
| `precipitation`             | 合計降水量     |
| `weather_code`              | 代表天気コード   |
| `cloud_cover`               | 平均雲量      |
| `cloud_cover_low`           | 平均低層雲量    |
| `cloud_cover_mid`           | 平均中層雲量    |
| `cloud_cover_high`          | 平均高層雲量    |
| `visibility`                | 最小視程      |
| `wind_speed_10m`            | 平均風速      |
| `wind_direction_10m`        | 代表風向      |
| `wind_gusts_10m`            | 最大突風      |
| `comment`                   | 生成コメント    |
| `line_sent`                 | LINE送信成否  |
| `error_message`             | エラー内容     |

## 7.3 実測ログ

実測ログはGoogleフォームで収集する想定とする。
予測ログと突合しやすいように、Googleフォームには以下の項目を含める。

| 項目    | 入力形式              |
| ----- | ----------------- |
| 日付    | 日付                |
| 記録時刻  | 時刻                |
| 空模様評価 | ◎ / ○ / △ / ×     |
| 夕焼け評価 | ◎ / ○ / △ / ×     |
| 快適度評価 | ◎ / ○ / △ / ×     |
| 風の体感  | 弱い / ちょうどよい / 強い  |
| 蒸し暑さ  | なし / ややあり / かなりあり |
| 写真    | ファイルアップロード        |
| メモ    | 自由記述              |

---

## 8. GitHub Actions要件

## 8.1 自動実行

`.github/workflows/daily_chill.yml` を作成する。

```yaml
name: Daily Zushi Chill Index

on:
  schedule:
    - cron: "7,22,37 4 * * *"  # 13:07/13:22/13:37 JST, displayed as 13:00
    - cron: "7,22,37 8 * * *"  # 17:07/17:22/17:37 JST, displayed as 17:00
  workflow_dispatch:

jobs:
  run:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: |
          pip install -e ".[dev]"

      - name: Run chill index
        env:
          LOCATION_NAME: ${{ secrets.LOCATION_NAME }}
          LATITUDE: ${{ secrets.LATITUDE }}
          LONGITUDE: ${{ secrets.LONGITUDE }}
          LINE_CHANNEL_ACCESS_TOKEN: ${{ secrets.LINE_CHANNEL_ACCESS_TOKEN }}
          LINE_TARGET_ID: ${{ secrets.LINE_TARGET_ID }}
          GOOGLE_FORM_URL: ${{ secrets.GOOGLE_FORM_URL }}
          STORAGE_BACKEND: ${{ secrets.STORAGE_BACKEND }}
          GOOGLE_SHEETS_SPREADSHEET_ID: ${{ secrets.GOOGLE_SHEETS_SPREADSHEET_ID }}
          GOOGLE_SERVICE_ACCOUNT_JSON: ${{ secrets.GOOGLE_SERVICE_ACCOUNT_JSON }}
        run: |
          python -m zushi_chill.main
```

## 8.2 手動実行

`workflow_dispatch` により、GitHub UIから手動で実行可能にする。

将来的には以下の入力を追加してもよい。

```yaml
workflow_dispatch:
  inputs:
    dry_run:
      description: "LINE送信せずログだけ出す"
      required: false
      default: "false"
```

---

## 9. 環境変数

`.env.example` を作成する。

```txt
# Location
LOCATION_NAME=逗子海岸
LATITUDE=35.2956
LONGITUDE=139.5736
TIMEZONE=Asia/Tokyo

# LINE
LINE_CHANNEL_ACCESS_TOKEN=
LINE_TARGET_ID=

# Form
GOOGLE_FORM_URL=

# Storage
STORAGE_BACKEND=csv
GOOGLE_SHEETS_SPREADSHEET_ID=
GOOGLE_SERVICE_ACCOUNT_JSON=

# Runtime
DRY_RUN=false
LOG_LEVEL=INFO
```

---

## 10. エラーハンドリング要件

### 10.1 Open-Meteo API取得失敗

* 最大3回リトライする
* リトライ間隔は指数バックオフにする
* 最終失敗時は処理を異常終了する
* LINE送信は行わない
* GitHub Actionsのログにエラーを出す

### 10.2 LINE送信失敗

* HTTPステータスコードとレスポンス本文をログに出す
* 保存先には `line_sent=false` として記録する
* 処理全体は異常終了扱いにする

### 10.3 Google Sheets保存失敗

* LINE送信前に保存する場合：保存失敗時はLINE送信しない
* LINE送信後に保存する場合：保存失敗をログに出す
* MVPでは「保存 → LINE送信」の順を推奨する

### 10.4 データ欠損

* 必須変数が欠損している場合は異常終了
* 欠損許容する変数は設定で定義可能にする
* 欠損値を0として扱わない

---

## 11. テスト要件

## 11.1 単体テスト

### `scoring.py`

以下をテストする。

* Sunset期待度が0〜100に収まる
* Chill指数が0〜100に収まる
* 低層雲が多い場合にSunset期待度が下がる
* 高層雲が適度な場合にSunset期待度が上がる
* 降水確率が高い場合に両指数が下がる
* 強風時にChill指数が下がる
* 体感温度22〜28℃で体感温度スコアが高くなる
* 体感温度34℃超で体感温度スコアが低くなる

### `message_builder.py`

以下をテストする。

* 必須項目がすべて含まれている
* 日付・時刻がJSTで表示される
* GoogleフォームURLが含まれる
* スコアに応じたコメントが出る

### `weather_client.py`

以下をテストする。

* Open-Meteoレスポンスを正しくパースできる
* 日没時刻を取得できる
* 日没前後の評価時間帯を抽出できる
* 欠損データ時に例外を出す

## 11.2 統合テスト

* fixtureのOpen-MeteoサンプルJSONからスコア算出できる
* DRY_RUN時にLINE送信を行わず、メッセージ本文だけ出力できる
* CSV保存ができる
* Google Sheets保存はmockで確認する

---

## 12. CLI要件

以下のように実行できること。

```bash
python -m zushi_chill.main
```

オプション例：

```bash
python -m zushi_chill.main --dry-run
python -m zushi_chill.main --date 2026-06-01
python -m zushi_chill.main --run-time 13:00
```

MVPでは `--dry-run` の実装を必須とする。
`--date` と `--run-time` は可能であれば実装する。

---

## 13. 受け入れ条件

## 13.1 必須受け入れ条件

* GitHub Actionsで13:00 JSTと17:00 JSTに自動実行される
* 手動実行できる
* Open-Meteoから逗子海岸の気象データを取得できる
* 日没時刻を取得できる
* 日没前後の時間帯でデータを集計できる
* Sunset期待度が算出される
* Chill指数が算出される
* LINEグループへテキスト投稿される
* 算出結果がログ保存される
* `--dry-run` でLINE送信なしの確認ができる
* pytestが通る
* READMEにセットアップ手順が記載されている

## 13.2 品質条件

* シークレット情報をコードに直書きしない
* 例外発生時に原因が分かるログを出す
* スコア計算ロジックは関数化し、テスト可能にする
* APIクライアント、スコアリング、LINE送信、保存処理を分離する
* MVP段階ではLLMに依存しない
* 画像生成処理を含めない
* SNS投稿処理を含めない

---

## 14. READMEに記載する内容

`README.md` には以下を記載する。

* プロジェクト概要
* MVPの目的
* 外部公開向け予報サービスではないこと
* セットアップ手順
* LINE Messaging APIの準備
* GitHub Secretsの設定
* ローカル実行方法
* dry-run方法
* GitHub Actions実行方法
* Google Sheets連携方法
* 6月中の検証運用フロー
* 実測評価の記録方法
* スコア計算式の説明
* 今後の改善方針

---

## 15. 6月の運用フロー

### 15.1 毎日の流れ

1. 13:00 JSTに自動通知
2. スタッフが内容を確認
3. 17:00 JSTに夕方直前通知
4. 日没前後にスタッフが実際の空模様・夕焼け・快適度を確認
5. Googleフォームに実測評価を入力
6. 必要に応じて写真をアップロード

### 15.2 6月末の分析対象

以下の乖離を確認する。

| パターン                 | 意味         |
| -------------------- | ---------- |
| Sunset期待度80以上だが実測△/× | 夕陽期待度が過大評価 |
| Sunset期待度50未満だが実測◎/○ | 夕陽期待度が過小評価 |
| Chill指数80以上だが快適度△/×  | 滞在快適度が過大評価 |
| Chill指数50未満だが快適度◎/○  | 滞在快適度が過小評価 |

### 15.3 調整対象

6月末に以下を調整する。

* 低層雲ペナルティ
* 高層雲ボーナス
* 中層雲ボーナス
* 湿度スコア
* 風スコア
* 降水リスク上限
* Sunset期待度のChill指数への寄与率

---

## 16. 法務・表現上の注意

本MVPは内部検証用であり、外部向けに「天気予報」「気象予報」「確実に夕陽が見える」といった表現を行わない。

正式なSNS運用に移行する場合も、以下の表現を推奨する。

| 避けたい表現          | 推奨表現        |
| --------------- | ----------- |
| 天気予報            | 来店参考指数      |
| 雨は降りません         | 雨リスクは低め     |
| 夕陽が見えます         | 夕陽期待度は高め    |
| SunSet Chill 予報 | 逗子サンセットチル指数 |
| 確実におすすめ         | 今日は過ごしやすそう  |

一般公開・継続運用する場合は、必要に応じて気象業務法・予報業務許可・気象予報士関与の要否を確認する。

---

## 17. 将来拡張

MVP後に検討する拡張は以下。

* SNS投稿用の短文生成
* Instagramストーリーズ用画像生成
* X投稿用テキスト生成
* 過去実測データに基づく重み調整
* LightGBM等によるスコア補正
* Webカメラ画像による空模様判定
* 複数地点対応
* 管理画面
* スタッフ入力のLINE Webhook連携
* 来店数・クーポン利用数との相関分析

---

## 18. Codexへの実装指示

この要件に基づき、まずは以下の順で実装する。

1. Pythonプロジェクトの雛形を作成する
2. Open-Meteo APIクライアントを実装する
3. 日没前後の対象時間帯抽出ロジックを実装する
4. Sunset期待度とChill指数の計算ロジックを実装する
5. LINE投稿文生成ロジックを実装する
6. LINE Messaging APIクライアントを実装する
7. CSV保存を実装する
8. Google Sheets保存を可能であれば実装する
9. GitHub Actionsを設定する
10. pytestを追加する
11. READMEと `.env.example` を整備する

初回実装では、Google Sheets連携よりもCSV保存とLINE通知の安定動作を優先する。
Google Sheets連携が複雑になる場合は、CSV保存までをMVP完了条件としてよい。
