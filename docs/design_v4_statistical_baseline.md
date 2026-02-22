# v4 差分設計メモ: 統計的ベースライン・レジーム適応・エコーチェンバー補正

## 概要

v3 → v4 で追加された4つのレイヤーを文書化する。
目的: ナラティブに騙されないための認知健全性レーダーとしての機能強化。

---

## Phase 1: カテゴリ正常値ベースライン層

### 変更理由
v3 では固定閾値（AI比率 > 50% で警告等）を使用していたが、
市場状態によって「正常」な分布は変動する。
統計的ベースライン（移動平均 + 標準偏差）に基づく動的な異常検出に移行。

### 新規モジュール
**`app/enrichers/narrative_baseline.py`**

| 関数 | 入出力 | 説明 |
|------|--------|------|
| `compute_category_baselines(db, windows, reference_date)` | DB → dict | 7/30/90日窓で各カテゴリのμ・σ・正常範囲を算出 |
| `compute_category_zscore(current_pct, baselines, window)` | float, dict → dict | 現在値と統計値からz-scoreを計算 |
| `evaluate_narrative_health(current_dist, baselines, window, z_threshold)` | dict, dict → dict | 全カテゴリの健全性評価サマリーを生成 |

### 異常検出ロジック
```
z = (current_pct - mean) / std
|z| >= 2.0 → 異常（anomalous）
1.0 <= |z| < 2.0 → 注意（elevated）
|z| < 1.0 → 正常（normal）
```

正常範囲: `[max(0, mean - z_threshold * std), min(1, mean + z_threshold * std)]`

### DB変更
なし（既存の `narrative_snapshots` テーブルを参照）

### 設定
```yaml
baseline:
  windows: [7, 30, 90]
  z_threshold: 2.0
  min_samples: 3
```

### テンプレート変更
`structural.md.j2` に「統計的ベースライン評価」セクション追加:
- z-score テーブル（カテゴリ/現在値/平均/σ/z-score/正常範囲/判定）
- 健全性サマリー

---

## Phase 2: アーキテクチャ・レイヤー分離

### 変更理由
ベースライン計算・レジーム検出・エコーチェンバー補正は、
既存の分析ロジック（SIS, SPP, 因果チェーン等）とは独立したレイヤーとして機能する。
各レイヤーを独立モジュールとして分離し、テスト容易性と拡張性を確保。

### アーキテクチャ
```
[Data Collection] → [Detection] → [Enrichment] → [NEW: Baseline/Regime/Echo] → [SPP (regime-adapted)] → [Report]
                                                    ↑                              ↑
                                            narrative_baseline.py          regime_detector.py
                                            echo_chamber.py               (weights → spp.py)
```

### `__main__.py` の呼出し順序（run_daily）
```python
# Phase 4 (既存): Enrichment
shock_type = classify_shock(...)
sis = compute_sis(...)
narrative_category = classify_narrative_category(...)
ai_centricity = compute_ai_centricity(...)

# Phase 4.5 (NEW): Baseline / Regime / Echo
baselines = compute_category_baselines(db, config.baseline.windows)
narrative_health = evaluate_narrative_health(current_dist, baselines)
regime_info = detect_market_regime(db, reference_date)
spp_weights = get_spp_weights(regime_info["regime"])
echo_info = detect_echo_chamber(articles, posts)
for event in events:
    apply_echo_correction(event, echo_info)

# Phase 5 (modified): SPP with regime weights
compute_spp_batch(events, db, weights=spp_weights)
```

---

## Phase 3: SPPウェイト外出し + レジーム適応

### 変更理由
v3 の SPP は固定ウェイトだった。
市場レジーム（平時/高ボラ/引き締め）によって
構造変化の持続性を評価する際に重視すべき要素が異なる。

### 新規モジュール
**`app/enrichers/regime_detector.py`**

| 関数 | 入出力 | 説明 |
|------|--------|------|
| `detect_market_regime(db, reference_date, vol_threshold, declining_threshold)` | DB → dict | 実現ボラティリティからレジーム判定 |
| `get_spp_weights(regime_name, config_weights)` | str → dict | レジームに応じたSPPウェイトを返す |

### レジーム分類
```
avg_annualized_vol < 25%                          → normal（平時）
avg_annualized_vol >= 25%                         → high_vol（高ボラ）
avg_annualized_vol >= 25% AND declining_pct > 50% → tightening（引き締め）
```

ボラティリティ計算:
- 20営業日の終値から対数日次リターンを算出
- 日次σ × √252 で年率換算
- 全監視銘柄の平均を使用（VIX代替）

### レジーム別SPPウェイト

| 成分 | normal | high_vol | tightening |
|------|--------|----------|------------|
| consecutive_days | 0.25 | 0.15 | 0.20 |
| evidence_trend | 0.25 | 0.15 | 0.20 |
| price_trend | 0.15 | **0.35** | 0.25 |
| media_diffusion | 0.20 | 0.15 | 0.20 |
| sector_propagation | 0.15 | 0.20 | 0.15 |

**high_vol**: 価格変動自体が構造変化の信号となるため `price_trend` を最重視。
**tightening**: 全体的にバランスを取りつつ `price_trend` を若干上げる。

### `spp.py` の変更
```python
# v3
def compute_spp(event, db=None):
    w = _WEIGHTS  # 固定

# v4
def compute_spp(event, db=None, weights=None):
    w = weights or _WEIGHTS  # レジーム適応可能
```

### DB変更
新テーブル `regime_snapshots`:
```sql
CREATE TABLE IF NOT EXISTS regime_snapshots (
    date TEXT NOT NULL,
    regime TEXT NOT NULL,
    avg_volatility REAL,
    declining_pct REAL,
    regime_confidence REAL,
    created_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (date)
)
```

### 設定
```yaml
regime:
  vol_threshold: 0.25
  declining_threshold: 0.50
  weights:
    normal:
      consecutive_days: 0.25
      evidence_trend: 0.25
      price_trend: 0.15
      media_diffusion: 0.20
      sector_propagation: 0.15
    high_vol:
      consecutive_days: 0.15
      evidence_trend: 0.15
      price_trend: 0.35
      media_diffusion: 0.15
      sector_propagation: 0.20
    tightening:
      consecutive_days: 0.20
      evidence_trend: 0.20
      price_trend: 0.25
      media_diffusion: 0.20
      sector_propagation: 0.15
```

### テンプレート変更
`structural.md.j2`:
- 「市場レジーム」セクション追加（レジーム名/ボラティリティ/下落比率/信頼度/適用ウェイト）

`weekly.md.j2`:
- 「市場レジーム推移」セクション追加（日付/レジーム/ボラティリティ/下落比率/信頼度テーブル）

---

## Phase 4: メディア・エコーチェンバー簡易補正

### 変更理由
同一ニュースが複数メディアで報道されると、独立した裏付けに見えてしまう。
エコーチェンバー（情報源の重複）を検出し、SPP の media_diffusion 成分を補正する。

### 新規モジュール
**`app/enrichers/echo_chamber.py`**

| 関数 | 入出力 | 説明 |
|------|--------|------|
| `detect_echo_chamber(articles, posts, similarity_threshold)` | list, list → dict | タイトル類似度 + URL参照でエコークラスタを検出 |
| `apply_echo_correction(event, echo_info)` | event, dict → None | イベントに補正係数を適用 |

### エコー検出ロジック
1. **タイトル類似度**: Jaccard距離（ストップワード除去後の単語集合）
   - 類似度 >= 0.7 → 同一クラスタ
2. **URL参照グラフ**: 記事本文中に他記事のURLが含まれるか
   - 参照関係 → 同一クラスタ
3. **Union-Find** で連結成分を構築

### 補正係数
```python
correction_factor = max(0.5, independent_sources / total_sources)
```
- 下限 0.5: 完全なエコーチェンバーでも半分は信用する
- `independent_sources`: クラスタ数（各クラスタから1つだけ独立とみなす）

### イベントへの適用
```python
event["echo_chamber_ratio"] = echo_info["echo_ratio"]
event["independent_source_count"] = echo_info["independent_sources"]
# SPP計算時の media_evidence は correction_factor で乗算
```

### DB変更
`enriched_events` テーブルに2列追加（ALTER TABLE マイグレーション）:
- `echo_chamber_ratio REAL`
- `independent_source_count INTEGER`

### 設定
```yaml
echo_chamber:
  similarity_threshold: 0.7
  min_correction: 0.5
```

### テンプレート変更
`structural.md.j2` に「メディア・エコーチェンバー評価」セクション追加:
- 総ソース数/独立ソース数/エコー比率/補正係数
- エコークラスター一覧（タイトル + ソース名）

---

## 品質条件の達成状況

| 条件 | 状態 | 根拠 |
|------|------|------|
| 統計的異常検出が再現可能 | OK | z-score = (current - mean) / std で決定的。同一入力→同一出力 |
| レイヤー分離で分析ロジックがクリーン | OK | baseline/regime/echoは独立モジュール。既存enricherのシグネチャ変更なし |
| SPPがレジームで変化する | OK | `compute_spp(weights=...)` でレジーム別ウェイト注入。3レジーム定義済 |
| 新旧ロジックの差分が文書化されている | OK | 本メモ |

---

## テスト追加状況

| テストファイル | テスト数 | 対象 |
|---------------|---------|------|
| `tests/test_narrative_baseline.py` | 26 | ベースライン計算・z-score・健全性評価 |
| `tests/test_regime_detector.py` | 20 | レジーム検出・SPPウェイト・信頼度・バリデーション |
| `tests/test_echo_chamber.py` | 30 | タイトル類似度・URL参照・Union-Find・補正係数 |
| **合計** | **76** | |

全テスト: 306件 (既存230 + 新規76) すべてパス。

---

## ファイル変更一覧

### 新規ファイル (4)

| ファイル | 行数 | 用途 |
|---------|------|------|
| `app/enrichers/narrative_baseline.py` | ~170 | 統計的ベースライン層 |
| `app/enrichers/regime_detector.py` | ~305 | レジーム検出 + SPPウェイト |
| `app/enrichers/echo_chamber.py` | ~200 | エコーチェンバー補正 |
| `docs/design_v4_statistical_baseline.md` | - | 本メモ |

### 新規テストファイル (3)

| ファイル | テスト数 |
|---------|---------|
| `tests/test_narrative_baseline.py` | 26 |
| `tests/test_regime_detector.py` | 20 |
| `tests/test_echo_chamber.py` | 30 |

### 変更ファイル (8)

| ファイル | 変更内容 |
|---------|---------|
| `app/__main__.py` | baseline/regime/echo呼出し追加、SPPにweights渡し |
| `app/enrichers/spp.py` | `weights` パラメータ追加（既存動作は変更なし） |
| `app/database.py` | `regime_snapshots` テーブル、マイグレーション列2つ、メソッド2つ |
| `app/config.py` | `BaselineConfig`, `RegimeConfig`, `EchoChamberConfig` 追加 |
| `configs/config.yaml` | `baseline:`, `regime:`, `echo_chamber:` セクション |
| `app/reporter/daily_report.py` | 3パラメータ追加 (`narrative_health`, `regime_info`, `echo_info`) |
| `app/reporter/templates/structural.md.j2` | 3セクション追加 |
| `app/reporter/templates/weekly.md.j2` | レジーム推移セクション追加 |

---

## サンプル出力の確認ポイント

### 日次レポート (`2026-01-22_structural.md`)
- **統計的ベースライン評価**: z-scoreテーブル表示。全日AIのみのためσ=0で「データ不足」表示（正しい動作）
- **市場レジーム**: 平時検出、ボラティリティ0%（価格データが限定的なため。データ蓄積で精度向上）
- **エコーチェンバー評価**: 338ソース中330独立、エコー比率2%、5クラスタ検出

### 週次レポート (`2026-01-22_weekly.md`)
- **レジーム推移**: 1日分のみ（01-22のみregime_snapshots保存済）
- **監視比重提案**: 規制/金融/エネルギーの3カテゴリについて監視継続を推奨 + AI過集中警告
- **SPP Top3**: GOOGL, MSFT, CRWD（重複なし）
