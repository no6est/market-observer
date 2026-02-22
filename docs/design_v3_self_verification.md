# 設計メモ: v3 認知の自己検証装置

## 概要

v2「ナラティブ信頼性強化」から v3「認知の自己検証装置」への進化。
システムが自らの予測精度を事後検証し、メディア伝播経路を可視化し、
構造変化の持続確率を定量化する4機能を追加した。

**最終目標**: 「ナラティブ観測装置」ではなく「認知の自己検証装置」

---

## Phase 1: 自己検証ログ

### ファイル
- `app/enrichers/self_verification.py` (新規)

### 設計

#### 予測ログ保存 (`save_prediction_log`)
- 毎日の `run_daily` 実行時に、その日の状態をSQLite `prediction_logs` テーブルに記録
- 保存項目: 日付、AI比率、top1集中度、過熱アラート有無、トップ5イベント(JSON)
- テーブルは `CREATE TABLE IF NOT EXISTS` で自動作成（マイグレーション不要）

#### 事後検証 (`verify_past_predictions`)
- 対象日から `verification_window` 日後のデータを使って検証
- 3つの検証軸:
  1. **AI継続性**: 対象日以降にAI関連イベントが継続しているか
  2. **価格持続性**: トップイベントの価格変動が持続しているか
  3. **Tier1追随**: SNS起点の話題がTier1メディアに到達したか
- 判定ロジック:
  - 過熱警告あり + 3軸中2つ以上が非持続 → **TP**
  - 過熱警告あり + 持続していた → **FP**
  - 過熱警告なし + 異常なし → **TN**
  - 過熱警告なし + 後から異常発覚 → **FN**

#### 集計 (`compute_verification_summary`)
- 過去N日分のログを集計し、TP/FP/TN/FN + Precision/Recall を算出
- 分母ゼロの場合は `None` を返す

### 週次レポートへの表示
- 混同行列テーブル（TP/FP/TN/FN, Precision, Recall）
- 個別判定リスト（日付、判定、詳細説明）

---

## Phase 2: ナラティブ推移可視化

### ファイル
- `app/enrichers/narrative_chart.py` (新規)

### 設計

#### トレンドチャート (`generate_narrative_trend_chart`)
- matplotlib の折れ線グラフ（7日間×カテゴリ別）
- AI/LLM/自動化 は赤色・太線で強調（他カテゴリと視覚的に区別）
- X軸: 日付、Y軸: 比率(0-100%)
- 凡例を右上に配置

#### メディア拡散チャート (`generate_media_diffusion_chart`)
- 水平棒グラフ（伝播パターン別件数）
- パターン名は日本語ラベルに変換（SNSのみ、SNS→Tier2、等）

#### 共通仕様
- `matplotlib.use('Agg')` でヘッドレス描画
- 出力: PNG (150dpi)
- 毎回 `plt.close('all')` でメモリリーク防止
- 日本語フォントが未インストールの環境でもエラーにならない（警告のみ）

### 週次レポートへの埋め込み
- `![ナラティブ推移](charts/narrative_trend.png)` 形式で Markdown 埋め込み
- `chart_paths` が None の場合はセクション非表示

---

## Phase 3: メディアティア分解

### ファイル
- `app/enrichers/media_tier.py` (新規)

### 設計

#### ティア分類
- **Tier1**: reuters, bloomberg, wsj, ft, nytimes, apnews, bbc 等（11ドメイン）
- **Tier2**: techcrunch, arstechnica, theverge, wired 等（15ドメイン）
- **SNS**: reddit, hackernews のpost、URL未分類のソース
- ドメインリストは `evidence_scorer.py` の `_TIER1_DOMAINS`, `_TIER2_DOMAINS` を再利用

#### 拡散パターン判定 (`diffusion_pattern`)
| パターン | 条件 |
|----------|------|
| `tier1_direct` | Tier1 > 0 かつ SNS == 0 |
| `sns_to_tier1` | SNS > 0 かつ Tier1 > 0 |
| `sns_to_tier2` | SNS > 0 かつ Tier2 > 0 かつ Tier1 == 0 |
| `sns_only` | SNS > 0 かつ Tier1 == 0 かつ Tier2 == 0 |
| `no_coverage` | 全ティア == 0 |

#### SNSバイアス比率 (`compute_sns_bias_ratio`)
- `sns_count / total_sources` (0-1)
- SPP計算の入力として使用

### DBスキーマ変更
- `enriched_events` テーブルに5カラム追加:
  - `tier1_count REAL`, `tier2_count REAL`, `sns_count REAL`
  - `diffusion_pattern TEXT`, `spp REAL`
- 既存DBは `ALTER TABLE ADD COLUMN` で後方互換マイグレーション

---

## Phase 4: 構造持続確率 (SPP)

### ファイル
- `app/enrichers/spp.py` (新規)

### 設計

#### SPP算出式
```
SPP = Σ(weight_i × factor_i)  ∈ [0.0, 1.0]
```

| Factor | Weight | 算出方法 |
|--------|--------|----------|
| consecutive_days | 0.25 | 過去7日のイベント出現日数 / 7 |
| evidence_trend | 0.20 | evidence_score の推移（上昇傾向で加点） |
| price_trend | 0.20 | 価格変動の持続性（z_score ≥ 2.0 で加点） |
| media_diffusion | 0.20 | メディア浸透度（Tier1到達で最高点） |
| sector_propagation | 0.15 | 同セクター波及の有無（propagation_targets数） |

#### factor詳細

**consecutive_days_factor**: DB内の過去7日でこの銘柄がイベントとして出現した日数。
毎日出現 = 1.0、初回のみ = 0.14。

**evidence_trend_factor**: evidence_score を直接使用。
高い裏付けスコア = 構造変化の持続性が高い。

**price_trend_factor**: z_score をシグモイド関数で正規化。
z ≥ 3.0 → 0.95、z = 2.0 → 0.5、z < 1.0 → 0.12。

**media_diffusion_factor**: 拡散パターンに基づくスコア。
tier1_direct/sns_to_tier1 = 1.0、sns_to_tier2 = 0.6、sns_only = 0.3、no_coverage = 0.1。

**sector_propagation_factor**: propagation_targets の数に基づく。
3件以上 = 1.0、2件 = 0.67、1件 = 0.33、0件 = 0.0。

#### バッチ処理 (`compute_spp_batch`)
- 日次パイプラインでは、イベント群を一括計算
- DB永続化前に呼出し、各イベントに `spp` フィールドを付与

### レポート表示
- **日次**: 構造インパクトランキングにSPPカラム追加
- **週次**: SPP Top3テーブル（銘柄、SPP、ショックタイプ、伝播パターン、サマリー）

---

## パイプライン統合

### `app/__main__.py` の変更箇所

```
_enrich_events():
  1. shock_classifier    (既存)
  2. impact_scorer       (既存)
  3. evidence_scorer     (既存)
  4. media_tier          ← NEW: tier1_count, tier2_count, sns_count, diffusion_pattern
  5. narrative_classifier (既存)
  6. ai_centricity       (既存)

run_daily():
  1. collect → detect → enrich (上記)
  2. compute_spp_batch    ← NEW: spp フィールド付与
  3. persist to DB
  4. narrative_concentration (既存)
  5. non_ai_highlights   (既存)
  6. narrative_overheat   (既存)
  7. save_prediction_log  ← NEW: 予測ログ保存
  8. generate reports

run_weekly():
  1. compute_weekly_analysis (既存、propagation_structure/spp_top3 追加)
  2. compute_verification_summary ← NEW: 事後検証集計
  3. generate_charts           ← NEW: チャート生成
  4. generate_weekly_report (chart_paths/verification_summary 込み)
```

---

## テスト

| テストファイル | テスト数 | カバレッジ |
|---------------|---------|------------|
| `tests/test_media_tier.py` | 10 | ティア分類、拡散パターン判定、SNSバイアス比率 |
| `tests/test_spp.py` | 7 | 各factor、バッチ処理、DB有無 |
| `tests/test_self_verification.py` | 10 | ログ保存/取得、検証ロジック、集計、精度計算 |
| `tests/test_narrative_chart.py` | 6 | チャート生成、空データ、ファイル出力 |
| `tests/test_weekly_analysis.py` (更新) | +2 | propagation_structure、spp_top3 キー |

**全テスト: 230件 (197 + 33新規)、全パス**

---

## 成果物

| ファイル | 種別 |
|---------|------|
| `reports/sample_structural_v3.md` | 日次サンプルレポート |
| `reports/sample_weekly_v3.md` | 週次サンプルレポート |
| `reports/charts/narrative_trend.png` | ナラティブ推移チャート |
| `reports/charts/media_diffusion.png` | メディア拡散チャート |

---

## 評価

### ゴール1: 自己検証ループ
- **達成度**: prediction_logs テーブルへの自動記録、3軸検証、TP/FP/TN/FN + Precision/Recall 算出が実装済み
- **制約**: 実データでの検証にはDBに7日以上のデータ蓄積が必要

### ゴール2: ナラティブ推移の可視化
- **達成度**: 7日間の折れ線グラフ + メディア拡散棒グラフを自動生成、週次レポートに埋め込み
- **制約**: 日本語フォント未インストール環境ではグリフが□表示（機能には影響なし）

### ゴール3: メディアティア分解
- **達成度**: 全イベントにTier1/Tier2/SNSカウント + 拡散パターンを付与、週次で伝播構造テーブル表示
- **制約**: ドメインリストは手動管理（将来的に外部設定化可能）

### ゴール4: 構造持続確率 (SPP)
- **達成度**: 5要素重み付きスコアを算出、日次ランキングにSPP列追加、週次でTop3テーブル表示
- **制約**: 重みは現在ハードコード（config化は将来タスク）
