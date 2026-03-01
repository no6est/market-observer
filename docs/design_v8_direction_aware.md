# 設計メモ: v8 方向性対応市場応答

## 概要

v7「市場応答構造」から v8「方向性対応市場応答」への進化。
v7では「ナラティブに市場がどう応えたか」を時間軸で可視化したが、
v8では**応答の方向性（上昇/下落）と市場環境（レジーム）を組み込み、
ナラティブの疲弊を検出する**。

**目的**: 応答構造の理解を「方向」「文脈」「寿命」の3軸で深化。

**設計方針**: 全変更は `market_response.py` への追加的変更。既存セクション1-12は非破壊。月次レポートにセクション14-16を新設し、セクション9・13を拡張。

---

## v7との差分: 何が新しいか

| 観点 | v7（市場応答構造） | v8（方向性対応市場応答） |
|------|-------------------|------------------------|
| 反応ラグ | 遅延日数のみ計測 | **+ 価格方向（上昇/下落）+ LLMセンチメント + アライメント判定** |
| レジーム | 月間構成・遷移のみ | **+ レジーム別反応ラグクロス分析** |
| ナラティブ寿命 | 再編連鎖（消滅→台頭） | **+ 疲弊検出（惰性で残る空洞化ナラティブ）** |
| 応答分類 | 5型プロファイル | **7型プロファイル（+ 疲弊型・逆行型）** |
| LLM活用 | なし | **Geminiによるセンチメント一括分類** |

---

## レポート構成（16セクション）

| # | セクション | 由来 | 読み手が得る答え |
|---|-----------|------|----------------|
| 1-8 | v6と同一 | v6 | （変更なし） |
| 9 | ナラティブ→価格反応ラグ | v7 PHASE 1 | ナラティブは何日後に価格に反映されるか？**+ 方向性統計** |
| 10 | 前月ウォッチ銘柄フォローアップ | v7 PHASE 2 | （変更なし） |
| 11 | ナラティブ消滅・再編連鎖 | v7 PHASE 3 | （変更なし） |
| 12 | Early Drift 追跡評価 | v7 PHASE 4 | （変更なし） |
| 13 | 市場応答プロファイル | v7 PHASE 5 | 市場はどのような応答パターンを示したか？**7型に拡張** |
| **14** | **方向性分析詳細** | **v8 PHASE 1拡張** | **ナラティブと価格の方向は整合しているか？** |
| **15** | **Regime × Reaction Lag クロス分析** | **v8 PHASE 6** | **市場環境によって反応速度は変わるか？** |
| **16** | **ナラティブ疲弊検出** | **v8 PHASE 7** | **支配的なナラティブは空洞化していないか？** |

---

## 新 PHASE の設計

### PHASE 1拡張: 方向性分析

#### 1a. price_direction フィールド

`compute_reaction_lag()` の `event_lags` 各要素に追加:

- `price_direction`: `reaction_pct` の符号から決定
  - `reaction_pct > 0` → `"up"`, `< 0` → `"down"`, else `"flat"`

#### 1b. LLMセンチメント分類

新関数: `_classify_sentiment_batch(llm_client, events)`

- 各イベントの `summary` を Gemini に渡して `"positive"` / `"negative"` / `"unclear"` を取得
- 20件ずつチャンク分割してバッチ処理（トークン制限回避）
- `max_tokens=1024` で JSON 配列を返却させる
- LLM未設定時 or 失敗時 → 全て `"unclear"` にフォールバック（degraded mode）

#### 1c. Direction Alignment

新関数: `_compute_alignment(sentiment, price_direction)`

- `positive + up` = `"aligned"`, `negative + down` = `"aligned"`
- `positive + down` = `"contrarian"`, `negative + up` = `"contrarian"`
- `unclear` or `flat` = `"unknown"`

#### 1d. 統計拡張

`stats` に追加:
- `aligned_rate`: aligned / total（unknown 除外）
- `contrarian_rate`: contrarian / total（unknown 除外）

```python
# event_lags 各要素の拡張フィールド
{
    "ticker": str, "date": str,
    "lag_days": int | None, "reaction_pct": float, "reacted": bool,
    "price_direction": "up" | "down" | "flat",      # NEW
    "sentiment": "positive" | "negative" | "unclear", # NEW
    "direction_alignment": "aligned" | "contrarian" | "unknown",  # NEW
}
```

### PHASE 6: Regime × Reaction Lag クロス分析

新関数: `compute_regime_reaction_cross(db, days=30, reference_date=None)`

**レジームソース**: `regime_snapshots` テーブルから `date→regime` マップを構築。`enriched_events.regime` カラム（NULL が多い）ではなく、権威ある `regime_snapshots` を優先参照。フォールバック: `enriched_events.regime` → `"neutral"`。

**レジームキーの日本語化**: グルーピング時点で `_regime_ja` マッピングを適用。テーブル表示・notable_patterns ともに日本語。

```python
_regime_ja = {
    "normal": "平時", "high_vol": "高ボラ", "tightening": "引き締め",
    "bullish": "強気", "bearish": "弱気", "neutral": "中立",
}
```

**出力**:
```python
{
    "regime_stats": {
        "引き締め": {"event_count", "avg_lag", "immediate_rate", "no_reaction_rate"},
        "高ボラ": {...},
    },
    "notable_patterns": ["高ボラレジームでは即時反応率が高い (67%)"],
}
```

### PHASE 7: ナラティブ疲弊検出

#### 7a. `detect_narrative_exhaustion(db, days=30, reference_date=None)`

**3条件 AND**:
1. 同一ナラティブ 5日連続占有率 ≥ 30%
2. 裏付けスコア中央値 ≤ 0.3（`evidence_score` from enriched_events）
3. 直近3日の z_score 平均 ≤ 1.0（`anomalies` テーブル）

**設計意図**: 「話題が支配的だが、裏付けが薄く、異常シグナルも沈静化している」＝ 惰性で残っているだけの空洞化ナラティブを検出する。3条件 AND により偽陽性を抑制。

**z_score 取得**: `db.get_anomalies_by_date_range(ticker, start_date, end_date)` — v8で追加した新メソッド。

```python
{
    "exhaustion_candidates": [
        {
            "narrative_category": str,
            "dominant_days": int,
            "avg_share": float,
            "median_evidence": float,
            "avg_z_score": float,
            "related_tickers": [str],
        }
    ],
    "total_detected": int,
}
```

#### 7b. `evaluate_exhaustion_outcomes(db, exhaustion_result, reference_date, followup_days=14)`

- 検出から14日後に、ナラティブ占有率が20pt以上低下 → `"衰退確認"`
- それ以外 → `"継続中"`

```python
{
    "evaluations": [{"category", "detected_share", "current_share", "change_pt", "outcome"}],
    "stats": {"total", "decay_rate"},
}
```

### 応答プロファイル拡張: 5型 → 7型

| # | 型 | 条件（優先順位順） |
|---|----|--------------------|
| 1 | 再編型 | 消滅チェーン衰退カテゴリ該当 |
| 2 | **疲弊型** (NEW) | exhaustion 候補カテゴリに該当 |
| 3 | 無反応型 | 未反応 |
| 4 | **逆行型** (NEW) | `direction_alignment == "contrarian"` |
| 5 | 一時的過熱型 | lag ≤ 1 AND SPP < 0.3 |
| 6 | 即時反応型 | lag ≤ 1 AND SPP ≥ 0.3 |
| 7 | 遅延持続型 | lag ≥ 3 AND SPP > 0.5 |
| default | 即時反応型 | |

`compute_response_profile()` に新パラメータ:
- `exhaustion_result: dict | None = None`
- `direction_data: dict[(ticker,date), dict] | None = None`

---

## 変更ファイル一覧

| ファイル | 変更種別 | 内容 |
|---------|---------|------|
| `app/enrichers/market_response.py` | 修正 | PHASE 1拡張 + PHASE 6,7新設 + 7型分類 |
| `app/database.py` | 追加 | `get_enriched_events_history()` に `regime` 追加、`get_anomalies_by_date_range()` 新設 |
| `app/enrichers/monthly_analysis.py` | 修正 | `llm_client` パラメータ追加、result に4キー追加、セクション14-16配線 |
| `app/__main__.py` | 修正 | `run_monthly` に Gemini client 配線 |
| `app/reporter/templates/monthly.md.j2` | 追加 | セクション9方向性統計、セクション13→7型、セクション14-16新設 |
| `app/reporter/daily_report.py` | 追加 | `response_type_ja` に "疲弊型", "逆行型" |
| `tests/test_market_response.py` | 追加 | 26テスト新設（計64テスト） |
| `tests/test_monthly_analysis.py` | 修正 | expected_keys に v8 キー追加 |

### 変更しないファイル

| ファイル | 理由 |
|---------|------|
| `weekly_analysis.py` | v8は月次のみ。週次に影響なし |
| セクション1-8, 10-12 | 完全非破壊。既存ロジック・テンプレートに変更なし |
| `database.py` スキーマ | 新規テーブル不要。既存テーブルの SELECT 拡張のみ |

---

## LLM利用設計

- `compute_reaction_lag()` に optional パラメータ `llm_client: Any | None = None`
- `llm_client` が None → sentiment = `"unclear"`, alignment = `"unknown"`（LLMなしでも全機能動作）
- `__main__.py` の `run_monthly` が Gemini client を生成し `compute_monthly_analysis()` 経由で渡す
- バッチプロンプト（20件ずつ）:
  ```
  以下のイベントサマリーについて、市場センチメントを分類してください。
  各行に対して positive / negative / unclear のいずれかをJSON配列で返してください。
  配列の要素数は入力行数と一致させてください。

  1. "NVDA: Blackwell Ultra 発表で GPU 需要急増"
  2. "XOM: EU炭素規制で前日比-3.5%"
  → ["positive", "negative"]
  ```
- パース失敗 → そのチャンクのみ全 `"unclear"`

---

## テスト追加状況

| テストクラス | テスト数 | 対象 |
|-------------|---------|------|
| `TestReactionLagDirection` | 4 | price_direction up/down/flat, sentiment default |
| `TestSentimentBatch` | 3 | without LLM, with LLM success, LLM failure fallback |
| `TestAlignmentComputation` | 6 | aligned/contrarian/unknown の全組み合わせ |
| `TestAlignmentStats` | 1 | aligned_rate with LLM |
| `TestRegimeCross` | 5 | regime grouping, empty, notable patterns, neutral default, no_reaction |
| `TestExhaustion` | 6 | 3条件AND, high evidence blocks, short dominance blocks, empty, decay, continuing |
| `TestResponseProfile7Types` | 5 | exhaustion type, contrarian type, priority ordering, 7型分布, 再編最優先 |
| `TestDirectionIntegration` | 4 | fields present, no price data, LLM flow, mixed alignment stats |
| **合計** | **34** (テストファイル全体: 64) | |

全テスト: **432件**（既存398 + 新規34）すべてパス。

---

## 既知の制約

### センチメント分類のデータ品質

現在の `enriched_events.summary` には異常検知メタデータ（「36件の検出(倍率×20.0倍)」「前日比+4.01%の価格変動」等）が格納されており、ニュース記事のような感情表現を含まない。LLM は正しくこれらを `"unclear"` と分類する。

**有効化に必要な拡張**（優先度順）:
1. **source_text 保存**: collector で取得した RSS 記事タイトルや Reddit 投稿文を `enriched_events` に紐付け保存
2. **anomaly ↔ news リンク**: 検知した anomaly と同日・同銘柄のニュースを自動マッチング
3. **原文永続化**: collector 段階で取得したテキストを DB に永続化し、sentiment 分類の入力に使用

### 疲弊検出のゼロ検出

3条件 AND が厳しいため、現データでは検出なしが正常。特に AI/LLM/自動化カテゴリは C1（5日連続占有 ≥ 30%）を通過するが、C2（evidence 中央値 ≤ 0.3）と C3（z_score 平均 ≤ 1.0）で脱落する。これは「証拠に裏付けられ異常も活発」な状態であり、「疲弊」ではないため妥当。

---

## 品質条件の検証結果

### 因果断定の禁止
- 全新関数: 「共起/応答」言語のみ使用
- セクション14-16: 「方向性分析」「クロス分析」「疲弊検出」— 因果を主張しない

### LLM非依存
- `llm_client=None` で全機能動作（degraded mode）
- テストは LLM なし / あり / 失敗の3パターンをカバー

### データ不足時フォールバック
- セクション14-16に `{% if %}` ガード + フォールバックメッセージ完備
- 疲弊検出ゼロは正常: 「検出されませんでした（正常状態）」

### 既存機能非破壊

| 項目 | 結果 |
|------|------|
| セクション1-12 | 全て正常動作（変更なし） |
| 日次レポート | 影響なし |
| 週次レポート | 影響なし |
| テスト398件 | 全パス（`test_monthly_analysis.py` の expected_keys のみ更新） |
