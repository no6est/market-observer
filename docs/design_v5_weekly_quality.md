# 設計メモ: v5 週次レポート品質改善

## 概要

v4「統計的ベースライン・レジーム適応」から v5「週次レポート品質改善」への進化。
週次レポートを「認知健全性レーダーの週次振り返り」として機能させるため、
7つの構造的ギャップを修正した。

**設計方針**: 既存アーキテクチャ維持（additive changes、既存シグネチャ不変、`{% if %}` ガード）

---

## 変更の目的

週次レポートの各セクションが読み手に返すべき答えを定義し、
それぞれのギャップを埋める。

| セクション | 読み手が得る答え |
|-----------|----------------|
| ショック分布 | 先週、何が起きたか？（全体像） |
| ナラティブ推移 | 何に目を奪われていたか？（注意配分の推移） |
| 転換点 | 週の途中で物語はどこで変わったか？（反転検出） |
| 前週比較 | 先週から今週へ、何がどう変わったか？（方向感） |
| 持続性テーブル | それは一過性か構造的か？（ノイズvs信号） |
| レジーム・ナラティブ同時変動 | 環境変化と注目は連動していたか？（見落とし補正） |
| 非AIハイライト | AI以外で見落としていたものは？（周辺視野） |
| 過熱検証 | 先週の警告は当たったか？（自己検証） |
| 仮説 | 来週、何に備えるべきか？（行動示唆） |
| 監視比重 | 来週、意識的に何を見るべきか？（次週フォーカス） |

---

## Gap 一覧と対応

| Gap | 内容 | 対応 |
|-----|------|------|
| 1 | 転換点検出が粗い（初日vs最終日のみ） | 持続条件付き最大スイング検出に変更 |
| 2 | 前週比較がない | WoW比較セクション新設 |
| 3 | 監視比重提案が最終日依存 | 週平均＋急変フラグの二層構造に変更 |
| 4 | イベント持続性が不可視 | ティッカー別出現日数・SPP推移テーブル新設 |
| 5 | レジーム×ナラティブが結びつかない | 同時変動検出セクション新設 |
| 6 | 仮説がテンプレート的 | 横断分析からの追加仮説生成 |
| 7 | 非AIハイライトの文脈不足 | ai_centricity・ショックタイプ・ナラティブ分類を追加表示 |
| — | 過熱検証ラベルが英語で誤読リスク | 日本語ラベルに変更 |

---

## Gap 1: 転換点検出の補正

### 変更理由

v4 の転換点は `trend[0]` vs `trend[-1]` の差分のみで判定しており、
週の途中での反転を検出できなかった。
また1日だけのスパイクをノイズとして除外する仕組みがなかった。

### 新規関数

**`_detect_turning_points(trend)`** — `weekly_analysis.py`

| 処理 | 説明 |
|------|------|
| 全隣接ペア走査 | カテゴリごとに全日の隣接ペアから最大スイングを抽出 |
| 閾値 | `abs(delta) >= 0.15`（15ポイント以上の変化） |
| 持続条件 | スイングの前日or翌日に同方向の変化があること |
| フォールバック | `len(trend) < 3` → 従来の first-vs-last 比較を維持 |

### 出力構造

```python
{
    "category": str,        # 変更なし
    "direction": str,       # 変更なし（"上昇"/"下降"）
    "delta": float,         # 変更なし
    "description": str,     # 期間を追加: 「02-18→02-22で22ポイント上昇」
}
```

### ノイズ耐性

```
Day1: 30% → Day2: 60% → Day3: 30%  (V字スパイク)
  最大スイング: Day1→Day2 (+30pt)
  持続チェック: Day0なし、Day2→Day3は-30pt（逆方向）→ 除外 ✓
```

---

## Gap 2: 前週比較（Week-over-Week）

### 変更理由

週次レポートに「前週との差分」がなく、方向感が掴めなかった。

### 新規関数

**`_compute_week_over_week(db, days, reference_date, ...)`** — `weekly_analysis.py`

- `reference_date - 7日` で前週の enriched_events / narrative / regime を取得
- DB側は既存メソッドの `reference_date` パラメータで対応。DB変更なし

### 新キー: `week_over_week`

```python
{
    "available": bool,            # 前週データが2日以上あれば True
    "shock_type_delta": {         # ショック種別ごとの増減
        "テクノロジーショック": {"current": 8, "previous": 6, "delta": 2},
        ...
    },
    "narrative_delta": {          # カテゴリ週平均の増減
        "AI/LLM/自動化": {"current_pct": 0.96, "previous_pct": 1.0, "delta_pt": -0.04},
        ...
    },
    "regime_shift": {             # 支配的レジームの変化
        "changed": bool,
        "previous_regime": str,
        "current_regime": str,
    },
    "event_count_delta": {"current": int, "previous": int, "delta": int},
    "previous_period": str,       # 例: "2026-02-08〜2026-02-14 (4日分)"
}
```

### フォールバック

`available=False` の場合、テンプレートで「前週データ不足 — 次週以降比較可能」を表示。

---

## Gap 3: 監視比重の週平均化＋急変フラグ

### 変更理由

v4 の `_generate_bias_corrections()` は `narrative_trend[-1]` （最終日のみ）を
参照しており、週の代表値として不適切だった。

### 変更箇所: `_generate_bias_corrections()` — `weekly_analysis.py`

| Before (v4) | After (v5) |
|-------------|------------|
| `narrative_trend[-1]["categories"]` | `_compute_narrative_average(narrative_trend)` |

### 新規ヘルパー

**`_compute_narrative_average(narrative_trend)`** — `weekly_analysis.py`

全日の categories を平均化し `dict[str, float]` を返す。
WoW 比較の前週平均計算でも再利用。

### 急変フラグ

最終日と週平均の乖離が **15pt 以上**のカテゴリを検出。

```python
action_dict["recent_surge"] = True       # bool
action_dict["latest_pct"] = 0.22         # float
```

テンプレート表示例:
```
⚡ 急変フラグ: 直近22%へ急変 — 動向注視を推奨
```

---

## Gap 4: イベント持続性トラッキング

### 変更理由

SPP Top3 だけでは「そのイベントが何日間継続しているか」が見えず、
一過性かどうかの判断ができなかった。

### 新規関数

**`_compute_event_persistence(enriched_history)`** — `weekly_analysis.py`

| 処理 | 説明 |
|------|------|
| `total_days` | **実観測日数**（暦日数ではなくデータがある日数） |
| ティッカー別集計 | 出現日数、最初/最新の SPP |
| SPP推移判定 | 差分 < 0.05 → 横ばい、> 0 → 上昇、< 0 → 下降 |

### 新キー: `event_persistence`

```python
[{
    "ticker": str,
    "days_appeared": int,
    "total_days": int,           # 実観測日数
    "spp_trend": str,            # "上昇"/"下降"/"横ばい"
    "latest_spp": float,
}]
```

SPP Top3 にも `days_appeared` を付加（テンプレート拡張は任意）。

---

## Gap 5: レジーム・ナラティブ同時変動

### 変更理由

v4 でレジーム推移とナラティブ推移は別セクションに表示されていたが、
両者の関連が可視化されていなかった。

### 新規関数

**`_compute_regime_narrative_cross(regime_history, narrative_trend)`** — `weekly_analysis.py`

| 検出条件 | 説明 |
|----------|------|
| レジーム遷移 + ナラティブ ±10pt | 遷移日に10pt以上のナラティブ変化がある場合 |
| レジーム異常 + ナラティブ集中 >60% | 高ボラ/引き締め時に特定カテゴリが60%超の場合 |

### 因果非断定

finding の文言は「同時期に観測」「共起」まで。
以下の語は**使用禁止**: 因果、影響、転換。

テンプレートに注記:
```
※ 同時期の観測であり、因果関係を示すものではありません
```

### 新キー: `regime_narrative_cross`

```python
[{
    "date": str,
    "finding": str,               # 因果語を含まない文
    "regime_from": str,
    "regime_to": str,
    "narrative_category": str,
    "delta": float,
}]
```

---

## Gap 6: 組織インパクト仮説の深化

### 変更理由

v4 の仮説はショック分布と転換点のみから生成されており、
持続性・レジーム変化・横断分析の知見が反映されていなかった。

### 新規関数

**`_generate_cross_hypotheses(...)`** — `weekly_analysis.py`

既存 `_generate_org_hypotheses()` は変更なし。
新関数の結果を `org_impact_hypotheses` に append。

### 仮説ソース

| # | ソース | 生成される仮説例 |
|---|--------|-----------------|
| 1 | レジーム×ナラティブ共起 | 「レジーム変化とナラティブシフトが同時期に発生 — 偶然か構造的連動かは継続観測が必要」 |
| 2 | 3日以上持続イベント | 「MSFTが4日間継続して観測 — 一過性ではなく構造的関心の可能性」 |
| 3 | SPP上昇銘柄 | 「CRWDのSPPが上昇傾向 — 構造変化が持続する可能性を示唆」 |
| 4 | WoWレジーム遷移 | 「レジームが平時→高ボラに変化 — リスク管理基準の見直しを検討する契機」 |

### `confidence_note`

各仮説にオプショナルな信頼度注記を付加:

| 条件 | 注記 |
|------|------|
| データ期間 < 7日 | 「短期データに基づく暫定的仮説」 |
| 前週比較不可 | 「前週データなしのため方向性は未確定」 |

テンプレートで `{% if h.confidence_note %}` ガード。

---

## Gap 7: 非AIハイライトの情報量追加

### 変更理由

v4 の非AIハイライトはティッカー・サマリー・スコアのみで、
「なぜ非AIなのか」「どのカテゴリか」が不明だった。

### 変更箇所

`weekly_analysis.py` L119-127: non_ai dict に `ai_centricity` を追加。

### テンプレート変更

各ハイライトに以下を追加表示:
- **ナラティブ分類**: （例: 金融/金利/流動性）
- **ショックタイプ**: 日本語マッピング済み
- **AI関連度**: （例: 6%）

---

## 過熱検証ラベルの日本語化

### 変更理由

`True Positive` / `False Positive` 等の英語ラベルは
非エンジニアの読者にとって誤読リスクが高い。

### テンプレート変更: `weekly.md.j2`

| Before | After |
|--------|-------|
| True Positive | 正警告（TP） |
| False Positive | 過剰警告（FP） |
| True Negative | 正常判定（TN） |
| False Negative | 見逃し（FN） |

verdict 表示も Jinja2 マッピングで日本語化。
セクション冒頭に注記追加:
```
※ "過熱警告を出したか"と"AI偏重が実際に続いたか"の検証
```

---

## バグ修正: SPP同日エントリの不整合

### 現象

同一ティッカー・同一日に複数エントリがある場合、
`spp_top3` と `event_persistence` で異なるエントリが選択されていた。

- `spp_top3`: `>` 比較 → 同日最初のエントリ（最大SIS）を保持
- `event_persistence`: `>=` 比較 → 同日最後のエントリに上書き

### 修正

`_compute_event_persistence` の latest_date 比較を `>=` → `>` に変更し、
`spp_top3` と同じ tie-breaking（最大SIS優先）に統一。

---

## 影響範囲

### 変更対象

| ファイル | 行数 | 変更内容 |
|---------|------|---------|
| `app/enrichers/weekly_analysis.py` | 836行 | 全7ギャップの分析ロジック修正・追加 |
| `app/reporter/templates/weekly.md.j2` | 248行 | 新セクション4つ追加 + ラベル修正 + 既存セクション拡張 |
| `tests/test_weekly_analysis.py` | 519行 | 新テスト12件 + mock拡張 |

### 変更しないファイル

| ファイル | 理由 |
|---------|------|
| `app/database.py` | 既存クエリメソッドの `reference_date` パラメータで対応済み |
| `app/reporter/daily_report.py` | weekly_analysis への依存なし。dict 通過のみ |
| `app/__main__.py` | run_weekly の呼出し構造に変更なし |
| `app/enrichers/self_verification.py` | 日本語化はテンプレート側で吸収 |
| `app/reporter/templates/daily.md.j2` | weekly と完全分離。影響なし |
| `app/reporter/templates/structural.md.j2` | weekly と完全分離。影響なし |

### daily レポートへの影響: **なし**

`compute_weekly_analysis()` は `run_weekly()` コマンドからのみ呼ばれる。
daily パイプライン（`run_daily()` → `generate_structural_report()`）は
weekly_analysis モジュールに一切依存していない。

---

## 新規関数一覧

| 関数 | ファイル | 用途 |
|------|---------|------|
| `_detect_turning_points(trend)` | weekly_analysis.py | 持続条件付き転換点検出 |
| `_compute_narrative_average(narrative_trend)` | weekly_analysis.py | 週平均ナラティブ分布計算 |
| `_compute_event_persistence(enriched_history)` | weekly_analysis.py | ティッカー別出現日数・SPP推移 |
| `_compute_week_over_week(db, days, ...)` | weekly_analysis.py | 前週比較 |
| `_compute_regime_narrative_cross(regime, narrative)` | weekly_analysis.py | レジーム×ナラティブ同時変動検出 |
| `_generate_cross_hypotheses(...)` | weekly_analysis.py | 横断分析からの追加仮説生成 |

---

## 新キー追加: `compute_weekly_analysis()` の返却値

| キー | 型 | Gap |
|------|-----|-----|
| `event_persistence` | `list[dict]` | 4 |
| `week_over_week` | `dict` | 2 |
| `regime_narrative_cross` | `list[dict]` | 5 |

既存キーへの変更:
- `bias_correction_actions`: 各 action に `recent_surge: bool`, `latest_pct: float` 追加（オプショナル）
- `non_ai_highlights`: 各ハイライトに `ai_centricity: float` 追加
- `org_impact_hypotheses`: 各仮説に `confidence_note: str` 追加（オプショナル）
- `spp_top3`: 各エントリに `days_appeared: int` 追加

---

## テスト追加状況

| テスト | 対象 | Gap |
|--------|------|-----|
| `test_turning_point_requires_persistence` | V字スパイク除外 | 1 |
| `test_turning_point_fallback_short_data` | 2日データのフォールバック | 1 |
| `test_bias_correction_uses_week_average_with_surge` | 週平均＋急変フラグ | 3 |
| `test_event_persistence_tracking` | 出現日数・SPP上昇検出 | 4 |
| `test_event_persistence_total_days_is_observed` | 実観測日数の正確性 | 4 |
| `test_non_ai_highlights_include_ai_centricity` | ai_centricityフィールド | 7 |
| `test_week_over_week_shock_delta` | ショック増減の正確性 | 2 |
| `test_week_over_week_unavailable` | 前週データ空のフォールバック | 2 |
| `test_week_over_week_regime_shift` | レジーム変化検出 | 2 |
| `test_regime_narrative_cross_analysis` | 同時変動検出＋因果語なし | 5 |
| `test_org_hypotheses_from_persistence` | 持続イベントからの仮説 | 6 |
| `test_org_hypotheses_from_regime_shift` | レジーム変化からの仮説 | 6 |

全テスト: **318件**（既存306 + 新規12）すべてパス。

---

## サンプル出力の確認ポイント (`2026-02-22_weekly.md`)

| セクション | 確認結果 |
|-----------|---------|
| 過熱検証 | 「正警告（TP）」「正常判定（TN）」等の日本語ラベル表示。注記あり |
| 非AIハイライト | JPM/LMTに「ナラティブ分類」「ショックタイプ」「AI関連度: 6%/1%」表示 |
| イベント持続性 | 8銘柄を「出現日数/観測日数」形式で表示。MSFT 4/4日 上昇 等 |
| 転換点 | 最終日のみの変化（AI 100%→78%）が持続条件で除外 → 「検出されませんでした」（正常動作） |
| 前週比較 | 比較期間明示（3日分）、ショック増減テーブル、ナラティブ変化テーブル表示 |
| レジーム・ナラティブ同時変動 | 引き締め×AI集中の共起を検出。免責注記あり。因果語なし |
| 監視比重 | 「週平均ナラティブ比率」表記。金融/AI両方に「⚡ 急変フラグ」表示 |
| 仮説 | 持続イベント4件＋SPP上昇3件の仮説生成 |
