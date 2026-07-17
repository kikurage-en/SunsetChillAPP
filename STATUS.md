# 検証運用ステータス

最終更新: 2026-07-17

このファイルは進行中の検証運用の現状と保留中の判断を記録する Truth Source。別セッション（コールドスタート）から現状を把握するための入口。仕様の詳細は `README.md`、算出ロジックはコードが正。

## 現在の構成（本番稼働中）

Sunset期待度は次の4層で算出・記録している（Chill指数は影響を受けない）。

- **層1**: Sunset期待度の雲量を、当日の日没方位へ `SUNSET_CLOUD_OFFSET_KM`（既定40km）離れた地点から取得（Chillは逗子海岸のまま）。ログ列 `sunset_cloud_*`。
- **層2**: 厚い中層雲キャップ（中層雲 55%→上限60、70%→上限40）。
- **層3**: 日没前（予測モード）で Vision 解析成功時、表示する `Sunset期待度` を式とVisionカメラAI予測のブレンドにする（`final = round((1-w)*sunset_score + w*vision_sunset_score)`、`w=SUNSET_VISION_BLEND_WEIGHT` 既定0.8）。**純式 `sunset_score` 列は上書きせず温存**し、表示値は別列 `final_sunset_score`。日没後（実況評価）・欠測・13:00 はブレンドせず式。
- **層4**: Sunsethue API（ray-model）の夕焼け品質予測を **log-only** 収集（列 `sunsethue_quality` 0-100 / `sunsethue_cloud_cover` % / `sunsethue_quality_text`）。スコアには影響しない独立ベンチマーク。`SUNSETHUE_ENABLED=true` で稼働。

**デプロイ**: `main` が Truth Source（GitHub Actions `daily_chill.yml` が `GITHUB_REF=main` で実行し、スコア算出・LINE送信・Sheets保存を行う）。Contabo cron は 13:00 / 17:00 を固定時刻、日没後を**日没+20分の動的予約**（毎朝8時に `scripts/schedule_sunset_capture.sh` が `at` 予約＝季節連動。2026-07-14 に固定19:20から切替）。予測ログは Google Sheets `predictions` ワークシート（42列）。

## 前向き検証（進行中）: 主予測信号の選抜

Sheets 各行で4信号を突合し、どれが日没後実測に最も近いかで主予測信号を選抜する。

- `sunset_score`（純式）
- `final_sunset_score`（式×Visionブレンド、表示値）
- `vision_sunset_score`（17:00=カメラAI予測 / 日没後=実況評価＝**ground truth**）
- `sunsethue_quality`（ray-model）

ground truth = 同一 `date` の日没後行の `vision_sunset_score`。数日〜1週間蓄積して判断する。

### データ点

| date | 実測(日没後Vision) | 式 | Sunsethue | Vision予測(17:00) | ブレンドfinal | 備考 |
|---|---|---|---|---|---|---|
| 2026-07-14 | 65 (partly_cloudy) | 100 (+35) | 30 (−35) | 65 (0) | 72 (+7) | Vision的中。式は快晴で過大、Sunsethueは悲観的 |
| 2026-07-15 | 55 (partly_cloudy) | 65 (+10) | 33 (−22) | 72 (+17) | 71 (+16) | 全予測が同方向にやや楽観(Sunsethueのみ悲観) |
| 2026-07-16 | 25 (overcast) | 60 (+35) | 11 (−14) | 55 (+30) | 56 (+31) | 全信号が外した日。Sunsethueが最も実測寄り |

### 中間集計（2026-07-17 時点、4信号が揃う N=3）

| 信号 | MAE | bias |
|---|---|---|
| Vision予測(17:00) | 15.7 | +15.7 |
| ブレンドfinal | 18.0 | +18.0 |
| Sunsethue | 23.7 | **−23.7（3/3日で悲観）** |
| 式(純) | 26.7 | +26.7 |

- 全期間（N=35、式とVisionのみ比較可能）: 式 MAE 25.0 / Vision MAE 14.1。**Visionが最良の単独信号**という傾向は継続。
- **Sunsethueのスケール不一致仮説**: 3/3日で一貫して悲観（bias −23.7）。同社の quality スケールが当プロジェクトのVision実測スケールと系統的にずれている可能性。絶対値でなく**順位相関（当たり日/外れ日の識別力）**で評価すべき。N≥10 で bias 補正後の MAE と順位相関を再計算する。
- 選抜判断は引き続きデータ不足（N=3）。**目安 N≥10（7月末頃）で判断**。

### 西地点距離（40km）の再検証 — 2026-07-17 実施、結論: 40km を維持

`SUNSET_CLOUD_OFFSET_KM=40` の妥当性を、本番と同一の式・幾何計算で N=35（6/12〜7/16）の距離スイープ（20〜70km を 5km 刻み＋経路平均＋経路max-low）により机上再検証した。

- 距離パラメータ自体は重要: 0〜25km は MAE 23+ で明確に劣る。**最適域は 30〜40km の平坦な盆地**（MAE 19.4〜20.6）。
- 最小は 35km（MAE 19.4、40km は 20.1）だが、差 0.7pt は**実質1日（7/07 の +35pt 改善）に由来し、別の1日（6/17 は 40km が35pt 優位）で相殺**される。35勝5日 vs 40勝4日。in-sample の N=35 でこの差に合わせるのは過学習（06-21 の N=1 フィットをドロップした判断と同型）。
- 経路平均・経路max-low（低層雲を経路最大値で評価）はいずれも単一 35〜40km 地点に勝てず。
- **結論: 40km を維持**。`SUNSET_CLOUD_OFFSET_KM` は Secret で無コード変更のまま調整可能なので、サンプルが増えた時点（目安 N≥50、8月末）で再スイープする。

## 保留中の判断（数日データ蓄積後に決める）

1. **日没後の表示** — 現状は日没後の見出し＝式（`sunset_score`）。
   - 案A: 現状維持（日没後見出し＝式）
   - 案B: 日没後の**表示** `final_sunset_score` を Vision実測にする（`sunset_score` 列は純式のまま温存＝検証の純度は保つ）
   - → 数日データを見て決定（2026-07-14 に保留を決定）。
   - **2026-07-17 追記: 3/3日で見出しと実測が食い違い**（7/14: 100 vs 65、7/15: 65 vs 55、7/16: 60 vs 25）。特に7/16は見出しB(60)に対し実測overcast(25)。実況通知としての整合性から案Bを支持する証拠が揃いつつある。ユーザー判断待ち。
2. **主予測信号の選抜**（式 / ブレンド / Vision / Sunsethue のどれを主にするか）→ 蓄積後。
3. **REQUIREMENTS.md** の現行仕様反映（任意。層1〜4は前例踏襲で未反映）。

## 参照

- 仕様: `README.md`（「スコア計算」「ライブカメラ画像の Vision 解析」「Sunsethue API による独立ベンチマーク」節）
- 設定: `.env.example`
- スケジューラ: `scripts/schedule_sunset_capture.sh`
