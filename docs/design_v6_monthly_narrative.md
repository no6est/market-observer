# 設計メモ: v6 月次ナラティブ分析

## 概要

v5「週次レポート品質改善」から v6「月次ナラティブ分析」への進化。
週次レポート4本を並べても見えない**月スケールの構造変化**を
可視化するための独立パイプラインを新設した。

**設計方針**: 既存モジュール再利用（additive changes）、DB変更なし、日次/週次に影響なし

---

## 週次との差分: 何が新しいか

| 観点 | 週次 | 月次 |
|------|------|------|
| 時間軸 | 7日 | 30日 |
| ナラティブ | スナップショット | **ライフサイクル**（誕生→成長→消滅の弧） |
| 仮説 | **生成**（最大3件） | **事後評価**（30日前の仮説が当たったか） |
| レジーム | 直近スナップショット | **弧と遷移**（安定度・遷移回数） |
| 持続性 | 7日間のノイズ/信号判定 | 30日間で**コア vs 一時的**を分離 |
| 前期比較 | 前週比 | **前月比**（銘柄入替を含む） |
| 行動示唆 | 来週の監視比重 | **来月の注目ポイント**（長期視座） |

---

## レポート構成（8セクション）

| # | セクション | 読み手が得る答え |
|---|-----------|----------------|
| 1 | ナラティブ・ライフサイクル | どの物語が生き残り、どれが消えたか？ |
| 2 | 仮説レトロスペクティブ | 30日前の仮説は当たったか？ |
| 3 | 市場レジーム推移 | 環境はどう変遷したか？ |
| 4 | 構造的持続性 | 何がノイズで何が信号か？ |
| 5 | 前月比較 | 先月から何が構造的に変わったか？ |
| 6 | ショック・伝播構造（月間） | どんな衝撃が多く、どう広がったか？ |
| 7 | 来月の注目ポイント | 来月、何に意識を向けるべきか？ |
| 8 | 月間ナラティブ推移 | 日々の注目配分はどう動いたか？ |

---

## 新規モジュール: `app/enrichers/monthly_analysis.py`

### メイン関数

**`compute_monthly_analysis(db, days=30, reference_date=None)`**

```python
{
    "narrative_lifecycle": dict,       # セクション1: カテゴリ別統計+軌道
    "lifecycle_stats": dict,           # セクション1: 集計統計
    "hypothesis_evaluations": list,    # セクション2: 個別評価結果
    "hypothesis_scorecard": dict,      # セクション2: スコアカード
    "regime_arc": dict,                # セクション3: 遷移・安定度・ボラ傾向
    "structural_persistence": dict,    # セクション4: コア/一時的銘柄
    "month_over_month": dict,          # セクション5: 前月差分
    "shock_type_distribution": dict,   # セクション6: ショック集計
    "propagation_structure": dict,     # セクション6: 伝播パターン集計
    "forward_posture": dict,           # セクション7: 来月の注目
    "narrative_trend": list,           # セクション8: 日次推移
    "regime_history": list,            # セクション3: 日次レジーム
    "period": str,                     # 分析期間文字列
}
```

### 処理フロー

```
1. DB取得: enriched_events(30d), narrative_history(30d), regime_history(30d)
2. ナラティブ・ライフサイクル: generate_monthly_summary() + _classify_trajectory()
3. 仮説レトロスペクティブ: evaluate_pending_hypotheses() + _compute_hypothesis_scorecard()
4. レジーム推移: _compute_regime_arc()
5. 構造的持続性: _compute_structural_persistence()
6. 前月比較: _compute_month_over_month()
7. ショック・伝播集計: Counter集計
8. 来月の注目: _generate_forward_posture()（1-7の結果を統合）
9. ナラティブ推移: 日次トレンドデータ構築
```

### 再利用した既存関数

| 関数 | 元モジュール | 用途 |
|------|------------|------|
| `_compute_narrative_average()` | weekly_analysis.py | 期間平均ナラティブ分布 |
| `_compute_event_persistence()` | weekly_analysis.py | 銘柄別出現日数+SPP推移 |
| `_SHOCK_TYPE_JA` | weekly_analysis.py | ショックタイプ日本語ラベル |
| `_ALL_CATEGORIES` | weekly_analysis.py | 8カテゴリ定数 |
| `generate_monthly_summary()` | narrative_archive.py | ライフサイクル基本統計 |
| `evaluate_pending_hypotheses()` | narrative_archive.py | 仮説事後評価 |

---

## 新規ヘルパー関数

### `_classify_trajectory(daily_series, period_days)`

カテゴリの30日間の軌道を7状態に分類。

```
判定順序（先に合致したものが適用）:
1. persistence_ratio < 0.1              → "不在"
2. persistence_ratio >= 0.8 + 分散<0.01 → "安定支配"
3. 前半不在 + 後半出現(>=10%)           → "新興"
4. 後半平均 > 前半平均 + 10pt           → "上昇"
5. 前半平均 > 後半平均 + 10pt           → "下降"
6. peak > avg*2.0 + 収束 < 5日         → "急騰消滅"
7. 上記いずれにも該当しない             → "不安定"
```

**設計判断**: 「新興」を「上昇」より先に判定する。
前半に存在しなかったカテゴリが後半に出現した場合、
数値的には「上昇」条件も満たすが、意味的に「新規出現」であり
「成長中」とは異なるため。

### `_compute_regime_arc(regime_history)`

```python
{
    "transitions": [{"date": str, "from": str, "to": str}],
    "dominant": str,               # 最頻レジーム
    "stability_score": float,      # 支配的レジームの占有率 (0-1)
    "volatility_trend": str,       # "上昇"/"下降"/"横ばい"/"不明"
    "regime_composition": {        # レジーム別日数・割合
        "normal": {"days": int, "pct": float},
        ...
    },
}
```

ボラティリティ傾向は前半/後半の平均ボラティリティを比較（閾値 0.005）。

### `_compute_structural_persistence(enriched_history)`

`_compute_event_persistence()` を再利用し、閾値で3分割。

```python
{
    "core_tickers": list,          # 出現率 60%以上
    "transient_tickers": list,     # 出現率 20%未満
    "turnover_rate": float,        # transient / all
    "all_persistence": list,       # 全銘柄データ（中間層含む）
}
```

### `_compute_month_over_month(db, days, reference_date, ...)`

`_compute_week_over_week()` と同設計。前月データを `reference_date - days` で取得。

```python
{
    "available": bool,             # 前月データ2日以上あれば True
    "narrative_delta": dict,       # カテゴリ平均の増減
    "shock_type_delta": dict,      # ショック種別の増減
    "regime_comparison": {         # 支配的レジームの変化
        "changed": bool,
        "previous_regime": str,
        "current_regime": str,
    },
    "ticker_turnover": {           # 銘柄入替
        "new": list,               # 今月のみ出現
        "gone": list,              # 前月のみ出現
        "continued": list,         # 両月出現
    },
    "event_count_delta": dict,
    "previous_period": str,
}
```

### `_compute_hypothesis_scorecard(evaluations, stats)`

```python
{
    "total_evaluated": int,
    "confirmed": int,              # 直近イベントに再出現 → 仮説的中
    "expired": int,                # 再出現なし → 仮説不発
    "inconclusive": int,           # ティッカー不明 → 判定不能
    "confirmation_rate": float,    # confirmed / total_evaluated
    "pending": int,                # まだ30日経過していない仮説数
}
```

### `_generate_forward_posture(lifecycle, regime_arc, persistence, mom)`

セクション1-6の分析結果を統合し、来月の行動指針を生成。

| 入力ソース | 生成内容 |
|-----------|---------|
| ライフサイクル「上昇」 | 注目度引き上げ提案 |
| ライフサイクル「新興」 | 新規監視対象追加提案 |
| ライフサイクル「下降」 | 見落としリスク警告 |
| MoM 銘柄入替「新規」 | ウォッチ銘柄追加 |
| 構造的持続性「コア」 | ウォッチ銘柄継続 |
| レジーム弧 | 安定度ベースのレジーム見通し |

---

## テンプレート: `monthly.md.j2`

### 品質ガード

全8セクション + サブセクションに `{% if %}` / `{% else %}` ガード。

| セクション | ガード条件 | フォールバック |
|-----------|-----------|--------------|
| 1. ライフサイクル | `{% if analysis.narrative_lifecycle %}` | 「データはありません」 |
| 2. 仮説レトロ | `{% if scorecard and total_evaluated %}` | 「評価対象の仮説はありませんでした」 |
| 3. レジーム推移 | `{% if analysis.regime_arc %}` | 「データはありません」 |
| 4. 構造的持続性 | `{% if %}` + コアなし分岐 | 「コア銘柄はありませんでした」 |
| 5. 前月比較 | `{% if available %}` | 「前月データ不足 — 翌月以降比較可能」 |
| 6. ショック・伝播 | 個別ガード × 2 | 各「データはありません」 |
| 7. 注目ポイント | `{% if analysis.forward_posture %}` | 「データはありません」 |
| 8. ナラティブ推移 | `{% if analysis.narrative_trend %}` | 「データはありません」 |

### 翻訳辞書

テンプレート変数としてレンダリング時に渡す（ハードコード回避）:
- `trajectory_ja`: 軌道分類の日本語ラベル
- `eval_ja`: 仮説評価結果の日本語ラベル
- `regime_ja`: レジームの日本語ラベル
- `pattern_ja`: 伝播パターンの日本語ラベル

---

## CLI: `run-monthly`

```
python -m app run-monthly [--date YYYY-MM-DD] [--config PATH] [--log-level LEVEL]
```

`run_weekly` と同パターン。出力: `{output_dir}/{date}_monthly.md`

| 属性 | 内容 |
|------|------|
| 独立実行 | `run_daily` / `run_weekly` の事前実行は不要 |
| DB操作 | 読取専用（`get_*` メソッドのみ） |
| 唯一の副作用 | `evaluate_pending_hypotheses()` が `hypothesis_logs.status` を更新 |
| ファイル名 | `_monthly.md`（daily `_structural.md`、weekly `_weekly.md` と非競合） |

---

## 品質条件の検証結果

### 因果断定の禁止

monthly_analysis.py / monthly.md.j2 の両方で禁止語ゼロ。
使用語は「推奨」「可能性」「傾向」のみ。

### 仮説最大3件制限

月次は仮説を**生成しない**（事後評価のみ）。制限は生成側（週次の `_generate_cross_hypotheses` → `[:3]`）で担保済み。
事後評価は監査目的のため全件開示が適切。

### Self-Verification との非干渉

| 項目 | 結果 |
|------|------|
| `prediction_logs` への書込み | なし |
| Self-Verification が読む enriched_events | 月次は読取のみ。競合なし |
| テーブル交差 | なし（Self-Verification = `prediction_logs`、月次 = `hypothesis_logs`） |

### データ不足時フォールバック

`compute_monthly_analysis()` の全キーが安全なデフォルト値で初期化
（空リスト / 空辞書 / `available: False`）。テンプレート側も全セクション `{% else %}` 完備。

### 日次/週次統合性

| 項目 | 結果 |
|------|------|
| DB パターン | 同一（`Database(cfg.database_path)`） |
| Config パターン | 同一（`load_config(config)`） |
| 共有関数 | 純関数のみ（副作用なし） |
| ファイル名衝突 | なし |
| 相互依存 | なし（各コマンド独立実行可能） |

---

## 影響範囲

### 変更対象

| ファイル | 変更種別 | 内容 |
|---------|---------|------|
| `app/enrichers/monthly_analysis.py` | **新規** | 全分析ロジック（6ヘルパー + メイン関数） |
| `app/reporter/templates/monthly.md.j2` | **新規** | 月次レポートテンプレート（8セクション） |
| `app/reporter/daily_report.py` | 追加 | `generate_monthly_report()` 関数1つ |
| `app/__main__.py` | 追加 | `run-monthly` CLIコマンド |
| `tests/test_monthly_analysis.py` | **新規** | テスト24件 |

### 変更しないファイル

| ファイル | 理由 |
|---------|------|
| `weekly_analysis.py` | ヘルパーを import するのみ。コード変更なし |
| `narrative_archive.py` | 既存関数を呼び出すのみ。コード変更なし |
| `database.py` | 既存 `get_*` メソッドで十分。DB変更なし |
| `self_verification.py` | テーブル交差なし。影響なし |
| `daily.md.j2` / `structural.md.j2` / `weekly.md.j2` | 完全分離。影響なし |

---

## テスト追加状況

| テストクラス | テスト数 | 対象 |
|-------------|---------|------|
| `TestComputeMonthlyAnalysis` | 3 | result_keys, empty_db, lifecycle_with_trajectory |
| `TestClassifyTrajectory` | 9 | 7状態 + 空系列 + 不安定フォールバック |
| `TestHypothesisScorecard` | 3 | 集計、空、stats-only |
| `TestRegimeArc` | 3 | 遷移検出、単一レジーム、空 |
| `TestStructuralPersistence` | 2 | コア/一時的分割、空 |
| `TestMonthOverMonth` | 2 | 利用可能、データ不足 |
| `TestReportRendering` | 1 | テンプレートレンダリング正常 |
| **合計** | **24** | |

全テスト: **368件**（既存344 + 新規24）すべてパス。

---

## サンプル出力の確認ポイント (`2026-02-22_monthly.md`)

| セクション | 確認結果 |
|-----------|---------|
| ライフサイクル | AI/LLM=安定支配(持続率100%)、金融=不在(8%)。統計テーブル表示 |
| 仮説レトロ | 30日+の仮説なし → 「評価対象なし」フォールバック表示 |
| レジーム推移 | 引き締め82%/高ボラ18%、遷移1件(高ボラ→引き締め)、安定度82%、ボラ上昇傾向 |
| 構造的持続性 | コア4銘柄(MSFT,CRWD,GOOGL,PLTR 100%)、一時的4銘柄、ターンオーバー率50% |
| 前月比較 | イベント+21件、レジーム変化(平時→引き締め)、新規4銘柄、継続4銘柄 |
| ショック・伝播 | テクノロジー23件、ナラティブシフト15件。伝播3パターン表示 |
| 注目ポイント | ウォッチ銘柄7件(新規+コア)。レジーム見通し: 安定だがボラ上昇傾向 |
| ナラティブ推移 | 12日分の日次カテゴリ推移データ |
