# 設計メモ: v7 市場応答構造

## 概要

v6「月次ナラティブ分析」から v7「市場応答構造」への進化。
v6まではナラティブの「検出」と「分類」が中心だったが、
v7では**ナラティブに市場がどう応えたか**を時間軸で可視化する。

**目的**: 市場予測ではなく、応答構造の理解。

**設計方針**: 全計算ロジックを `market_response.py` に集約。既存セクション1-8は非破壊。月次レポートにセクション9-13を追加。

---

## v6との差分: 何が新しいか

| 観点 | v6（月次ナラティブ） | v7（市場応答構造） |
|------|---------------------|-------------------|
| ナラティブ | ライフサイクル観測 | **ライフサイクル + 消滅/再編連鎖の検出** |
| 価格反応 | なし | **ナラティブ→価格の反応ラグ計測** |
| 前月追跡 | 銘柄入替の検出 | **ウォッチ銘柄の仮説強化/収束/反転判定** |
| 応答分類 | なし | **5型プロファイル（即時/遅延/過熱/無反応/再編）** |
| 初動追跡 | なし | **Early Drift の永続化と30日後評価** |
| チャート | ナラティブトレンド + 伝播 | **+ 反応ラグヒストグラム** |

---

## レポート構成（13セクション）

| # | セクション | 由来 | 読み手が得る答え |
|---|-----------|------|----------------|
| 1-8 | v6と同一 | v6 | （変更なし） |
| 9 | ナラティブ→価格反応ラグ | PHASE 1 | ナラティブは何日後に価格に反映されるか？ |
| 10 | 前月ウォッチ銘柄フォローアップ | PHASE 2 | 先月注目した銘柄はその後どうなったか？ |
| 11 | ナラティブ消滅・再編連鎖 | PHASE 3 | どのナラティブが消え、何に置き換わったか？ |
| 12 | Early Drift 追跡評価 | PHASE 4 | SNS初動シグナルはその後メディアに到達したか？ |
| 13 | 市場応答プロファイル | PHASE 5 | 市場はどのような応答パターンを示したか？ |

---

## 5 PHASE の設計

### PHASE 1: 反応ラグ分析 (`compute_reaction_lag`)

**ロジック**: 各イベントの ticker に対し、イベント日以降の価格データから ±2.0% を超えた最初の日を `lag_days` として計測。

```python
{
    "event_lags": [{"ticker", "date", "lag_days", "reaction_pct", "reacted"}],
    "stats": {
        "avg_lag": float,
        "median_lag": float,
        "immediate_rate": float,   # lag_days <= 1
        "delayed_rate": float,     # lag_days >= 3
        "no_reaction_rate": float,
    },
    "histogram_data": [(bucket_label, count), ...],
}
```

**バケット**: 0日, 1日, 2日, 3日, 4日, 5日, 6-10日, 11+日, 未反応

### PHASE 2: ウォッチ銘柄フォローアップ (`compute_watch_ticker_followup`)

**ロジック**: 前月のコア銘柄（出現率60%以上 or 平均SPP 0.5以上）を抽出し、今月との変化を判定。

**判定ルール**:
- `仮説強化`: curr_spp > prev_spp AND (price_change > 0 OR narrative_share増加)
- `収束`: curr_spp < prev_spp AND narrative_share減少 AND |price_change| < 2%
- `反転`: price_change の符号が前月トレンドと逆
- `再編連鎖`: ticker が今月の enriched_events に不在

**前提条件**: 前月期間に enriched_events が存在し、かつウォッチ基準を満たす銘柄があること。初回分析（前月データなし）ではフォールバック表示。

```python
{
    "available": bool,
    "followups": [{"ticker", "prev_spp", "curr_spp", "price_change_pct", "narrative_share_change", "outcome"}],
    "outcome_distribution": {"仮説強化": N, "収束": N, "反転": N, "再編連鎖": N},
}
```

### PHASE 3: ナラティブ消滅・再編連鎖 (`detect_narrative_extinction_chain`)

**ロジック**:
1. narrative_history を前半/後半に分割
2. 前半平均 - 後半平均 >= 5pt 減少のカテゴリ = declining
3. 後半平均 - 前半平均 >= 5pt 増加のカテゴリ = rising
4. declining × rising の各ペアについて、enriched_events の summary からバイグラム抽出
5. バイグラムの共起数 >= 2 → 再編連鎖候補

**バイグラム抽出**: CJK文字列 + ASCII英単語(2文字以上) から連続ペアを構成。

```python
{
    "chains": [{"declining_cat", "rising_cat", "shared_keywords", "overlap_score", "sample_events"}],
    "reorganization_map": {"declining_cat": ["rising_candidates"]},
}
```

### PHASE 4: Early Drift 追跡 (`track_early_drift_persistent` + `evaluate_drift_followups`)

**2つの関数に分離**:

- `track_early_drift_persistent`: `run_weekly` 内で呼び出し、drift候補を `hypothesis_logs` に `status='drift_pending'` で保存
- `evaluate_drift_followups`: `run_monthly` 内で呼び出し、30日以上前の drift_pending エントリを評価（Tier1到達?, 価格反応?）

```python
{
    "evaluations": [{"id", "ticker", "date", "tier1_arrived", "price_reacted", "outcome"}],
    "stats": {"total", "tier1_arrival_rate", "price_reaction_rate", "drift_success_rate"},
}
```

### PHASE 5: 市場応答プロファイル (`compute_response_profile`)

**分類ルール（優先順位順）**:
1. ticker が extinction chain の declining_cat に属する → `再編型`
2. lag_info なし or 未反応 → `無反応型`
3. lag_days <= 1 AND SPP < 0.3 → `一時的過熱型`
4. lag_days <= 1 AND SPP >= 0.3 → `即時反応型`
5. lag_days >= 3 AND SPP > 0.5 → `遅延持続型`
6. default → `即時反応型`

**PHASE 1 + PHASE 3 の結果に依存**（最後に計算）。

```python
{
    "event_profiles": [{"ticker", "date", "response_type", "evidence"}],
    "distribution": {"即時反応型": N, "遅延持続型": N, "一時的過熱型": N, "無反応型": N, "再編型": N},
    "distribution_pct": {"即時反応型": 0.xx, ...},
}
```

---

## 新規モジュール: `app/enrichers/market_response.py`

5 PHASE の全計算ロジックを格納。各関数は try/except で保護され、失敗時は安全なデフォルト値を返す。

### ヘルパー関数

| 関数 | 用途 |
|------|------|
| `_extract_bigrams(text)` | CJK+ASCII バイグラム抽出（PHASE 3用） |
| `_get_previous_watch_tickers(db, days, prev_ref)` | 前月ウォッチ銘柄の軽量抽出（再帰回避） |

---

## 変更ファイル一覧

| ファイル | 変更種別 | 内容 |
|---------|---------|------|
| `app/enrichers/market_response.py` | **新規** | 5 PHASE の全計算ロジック |
| `app/enrichers/monthly_analysis.py` | 追加 | result dict に5キー追加、セクション9-13の計算 |
| `app/enrichers/narrative_chart.py` | 追加 | `generate_reaction_lag_histogram()` + 全チャート英語化 |
| `app/enrichers/spp.py` | 修正 | `reference_date` パラメータ追加（バックフィル対応） |
| `app/database.py` | 追加 | `get_price_data_range()`, `get_drift_hypotheses()` |
| `app/reporter/daily_report.py` | 追加 | `response_type_ja`, `outcome_ja` 翻訳辞書 |
| `app/reporter/templates/monthly.md.j2` | 追加 | セクション9-13（全セクション `{% if %}` ガード付き） |
| `app/__main__.py` | 追加 | run_monthly: ラグチャート生成 / run_weekly: Drift永続化 |
| `scripts/backfill_daily.py` | **新規** | 過去日付のバックフィルユーティリティ |
| `tests/test_market_response.py` | **新規** | 30テスト |

### 変更しないファイル

| ファイル | 理由 |
|---------|------|
| `weekly_analysis.py` | v7は月次のみ。週次に影響なし |
| `database.py` スキーマ | 新規テーブル不要。既存テーブルのみ使用 |
| セクション1-8 | 完全非破壊。既存ロジック・テンプレートに変更なし |

---

## `spp.py` のバックフィル対応修正

### 問題

`compute_spp` 内の `_consecutive_days_factor` / `_evidence_trend_factor` が `db.get_enriched_events_history(days=7)` を `reference_date` なしで呼んでいた。これにより、バックフィル時（過去の日付を処理中）でも「今日から7日前」のデータを参照し、SPP が NULL になっていた。

### 修正

- `_consecutive_days_factor(event, db, reference_date=None)` — `reference_date` パラメータ追加
- `_evidence_trend_factor(event, db, reference_date=None)` — 同上
- `compute_spp(event, db=None, weights=None, reference_date=None)` — 上記に転送
- `compute_spp_batch(events, db=None, weights=None, reference_date=None)` — 同上
- `backfill_daily.py`: `event["spp"] = compute_spp(event, db=db, reference_date=up_to_date)` と戻り値をキャプチャ

### 影響

既存の `run_daily` / `run_weekly` は `reference_date=None` のままで動作するため、後方互換性あり。バックフィル時のみ明示的に日付を指定する。

---

## チャートの英語化

### 問題

matplotlibのデフォルトフォント（DejaVu Sans）がCJK文字をサポートしないため、日本語ラベルが豆腐化（文字化け）していた。

### 対応

全チャートのラベルを英語に変更。カテゴリ名はDBから日本語で渡されるため、描画時に `_CATEGORY_EN` 辞書で英語変換。

| 要素 | Before | After |
|------|--------|-------|
| トレンドチャートタイトル | ナラティブカテゴリ推移（7日間） | Narrative Category Trend (7 days) |
| 伝播チャートタイトル | ナラティブ伝播構造 | Narrative Diffusion Structure |
| ラグチャートタイトル | ナラティブ→価格反応ラグ分布 | Narrative -> Price Reaction Lag Distribution |
| バケットラベル | 0日, 1日, ..., 未反応 | 0d, 1d, ..., No Reaction |
| X軸 | 件数 | Count |
| 凡例カテゴリ | AI/LLM/自動化 | AI/LLM/Automation |

---

## バックフィルユーティリティ: `scripts/backfill_daily.py`

### 目的

`run_daily` は `datetime.utcnow()` 基準で検出を行うため、過去日付のデータ補完ができない。バックフィルスクリプトは既存の `price_data` テーブルから自己完結的に異常検出 + エンリッチメントを行う。

### 特徴

- **外部API呼び出しなし**: DB内の price_data のみ使用
- **自己完結的な異常検出**: `detect_anomalies_for_date()` を内蔵（detectors モジュールの時刻依存を回避）
- **既存エンリッチャー再利用**: shock_classifier, impact_scorer, narrative_classifier, evidence_scorer, media_tier, propagation, spp を全て呼び出し
- **SPP の reference_date 対応**: 処理中の日付を `compute_spp` に渡し、正確な履歴参照を保証

### 使用法

```bash
python scripts/backfill_daily.py --start 2025-11-20 --end 2026-02-22
```

### 価格データの拡張

price collector の `period` パラメータで取得期間を制御可能:

| period | 取得期間 | 用途 |
|--------|---------|------|
| `1mo` (デフォルト) | ~22営業日 | 日次運用 |
| `3mo` | ~62営業日 | バックフィル用拡張 |
| `6mo` | ~125営業日 | さらに長期の遡り |

---

## テスト追加状況

| テストクラス | テスト数 | 対象 |
|-------------|---------|------|
| `TestReactionLag` | 7 | 即時/遅延/未反応/統計/空データ/価格なし/ヒストグラム |
| `TestWatchTickerFollowup` | 5 | 強化/収束/反転/再編/前月なし |
| `TestExtinctionChain` | 5 | 検出/キーワードなし/バイグラム/空/マップ |
| `TestDriftTracking` | 4 | 永続化/Tier1/価格/成功率 |
| `TestResponseProfile` | 6 | 5型分類 + 分布合計 |
| `TestIntegration` | 3 | 全キー存在/テンプレート描画/PHASE5→1依存 |
| **合計** | **30** | |

全テスト: **398件**（既存368 + 新規30）すべてパス。

---

## 3期レポートによる実データ検証

yfinance `period="3mo"` で 2025-11-20〜2026-02-20 の62日分を取得し、バックフィル後に3期の月次レポートを生成して検証。

### データ規模

| 指標 | 値 |
|------|-----|
| price_data | 916行 / 62日 |
| enriched_events | 208件 / 53日 |
| SPP null | 0件（全208件に値あり） |

### セクション別検証結果

| セクション | 12月 (2025-12-22) | 1月 (2026-01-22) | 2月 (2026-02-22) |
|-----------|-------------------|-------------------|-------------------|
| **9. 反応ラグ** | 65件, 平均3.9日, 未反応0% | 57件, 平均3.7日, 未反応0% | 83件, 平均2.3日, 未反応23% |
| **10. ウォッチ評価** | データなし（初回） | **3銘柄**: MSFT反転, JPM反転, GOOGL仮説強化 | **3銘柄**: MSFT/GOOGL/JPM全て仮説強化 |
| **11. 再編連鎖** | データなし | **6件検出** (エネルギー→AI, 金融→AI 等) | 0件（AI支配でカテゴリ交替なし） |
| **12. Early Drift** | 評価対象なし | 評価対象なし | 評価対象なし |
| **13. 応答プロファイル** | 即時43%/過熱18%/遅延18%/再編21% | 即時46%/再編35%/遅延10%/過熱9% | 即時43%/過熱25%/無反応23%/遅延8% |

### 月間変化の読み取り

- **反応ラグ**: 12月→2月で平均3.9日→2.3日に短縮（市場の反応速度が向上）、ただし2月は未反応23%も出現
- **ウォッチ評価**: 1月→2月でGOOGLが2か月連続仮説強化（SPP 0.52→0.57→0.63）
- **再編連鎖**: 1月のみ検出（ナラティブ多様: AI 55%）、2月は AI 82%支配で交替パターン消失
- **応答プロファイル**: 再編型が1月35%→2月0%、無反応型が0%→23% — PHASE 3との連動を確認

### セクション12 (Early Drift) が全期間空の理由

**データ上妥当。** Early Drift の検出条件4つを全て同時に満たすイベントが存在しない。

```
条件1: narrative_category のシェア < 20%（マイナーカテゴリ）
条件2: cat_z >= 1.5（そのカテゴリの z-score が異常に高い）
条件3: diffusion_pattern == "sns_to_tier2"（SNS→Tier2伝播中）
条件4: ticker が price_change で反応していない（価格未反応）
```

**ボトルネック**: `sns_to_tier2` パターンの全24件が AI/LLM/自動化カテゴリ（日次シェア55-100%）であり、条件1（シェア < 20%）で全滅する。

| カテゴリ | sns_to_tier2 件数 | 日次シェア | 条件1通過? |
|---------|------------------|-----------|-----------|
| AI/LLM/自動化 | 24件 | 55-100% | No |
| エネルギー/資源 | 0件 | - | - |
| 金融/金利/流動性 | 0件 | - | - |
| 規制/政策/地政学 | 0件 | - | - |

非AIカテゴリがTier2メディアまで伝播する事例がなく、Drift条件が構造的に成立しない。RSSフィードからの記事収集が充実し、非AIカテゴリの `sns_to_tier2` イベントが発生すれば、Drift検出が動き始める見込み。

---

## 品質条件の検証結果

### 因果断定の禁止

- 全関数: 「共起/応答」言語のみ使用
- セクション11テンプレート: 明示注意書き（「因果関係を主張するものではありません」）
- PHASE 5: 「応答パターン」「観測された反応」等の表現のみ

### 仮説最大3件制限

v7 PHASEは仮説を**生成しない**（メトリクスのみ）。制限の対象外。

### データ不足時フォールバック

全5セクション(9-13)に `{% if %}` ガード + フォールバックメッセージ完備。
3期レポートで実際にフォールバック表示を確認:
- セクション10: 12月「前月データ不足または初回分析」
- セクション11: 2月「再編連鎖は検出されませんでした」
- セクション12: 全期間「評価対象はありません（初回分析または該当なし）」

### 既存機能非破壊

| 項目 | 結果 |
|------|------|
| セクション1-8 | 全て正常動作（変更なし） |
| 日次レポート | 影響なし |
| 週次レポート | Early Drift永続化のみ追加（レポート内容に変更なし） |
| テスト368件 | 全パス（`test_result_keys` のみ expected_keys に5キー追加） |
