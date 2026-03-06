# v10: ナラティブ遷移追跡 + ソース信頼性重み付け

> 設計日: 2026-03-07

---

## 概要

v10 では2つの新機能を追加:

1. **ナラティブ遷移追跡**: カテゴリ間の遷移パターン（declining × rising）を検出・蓄積し、過去パターンから遷移見通しを提供
2. **ソース信頼性重み付け (SRS)**: 既存の media_tier 分類にスコア重みを付与し、モメンタム計算とナラティブグラフに反映

既存の22セクションは全て維持。新セクション2つを挿入して24セクション構成。

---

## Feature A: ナラティブ遷移追跡

### 動機

既存の `narrative_track` は同一ナラティブの「継続」を追跡する。v10 の遷移追跡は「異なるナラティブ間の移行関係」を追跡する新機能。「AI話題が衰退するとき、次に何が台頭しやすいか？」という問いに統計的に答える。

### DB テーブル: `narrative_transitions`

```sql
CREATE TABLE IF NOT EXISTS narrative_transitions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    date          TEXT NOT NULL,
    from_category TEXT NOT NULL,
    to_category   TEXT NOT NULL,
    from_momentum REAL NOT NULL,
    to_momentum   REAL NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(date, from_category, to_category)
);
```

### 検出アルゴリズム

`detect_narrative_transitions(narrative_momentum, declining_threshold, rising_threshold)`:

1. momentum < declining_threshold（デフォルト -0.3）のカテゴリ集合 = declining
2. momentum > rising_threshold（デフォルト +0.3）のカテゴリ集合 = rising
3. 全ペア (declining × rising) を遷移として出力

`build_transition_outlook(today_momentum, transition_history, top_n=5)`:

1. 今日の dominant_category（today_count 最大）を特定
2. 過去の transition_history から from_category == dominant のレコードを集計
3. to_category 別の出現回数 / 合計 = 発生率
4. top_n 件を返す

### レポートセクション

- **セクション7: ナラティブ遷移**: 今日検出された遷移ペアのテーブル
- **セクション8: ナラティブ遷移見通し**: 過去パターンに基づく統計集計

---

## Feature B: ソース信頼性重み付け (SRS)

### 動機

既存の media_tier 分類は SIS/evidence_score に影響するが、イベントのカウント（モメンタム計算）には反映されない。SNSのみの低信頼イベントも Tier1 報道ありの高信頼イベントも同じ「1件」として扱われていた。

### SRS 計算式

```
base = tier_weights[diffusion_pattern]
    tier1_direct=1.0, sns_to_tier1=0.85, sns_to_tier2=0.60,
    sns_only=0.30, no_coverage=0.20

diversity_bonus = min(independent_source_count / diversity_source_cap, diversity_max_bonus)
echo_penalty = echo_chamber_ratio × echo_penalty_factor

SRS = clamp(0.0, 1.0, base + diversity_bonus - echo_penalty)
```

### 適用箇所

1. **モメンタム計算**: `compute_weighted_category_momentum()` — 生のカウントの代わりに SRS 重みを合算
2. **ナラティブグラフ**: 各ティッカーに SRS フィールドを追加表示
3. **DB 永続化**: enriched_events テーブルに srs カラムを追加

### パイプライン挿入位置

```
apply_echo_correction（既存）
↓
apply_srs_to_events（NEW: ここに挿入）
↓
compute_spp_batch（既存）
```

---

## ファイル一覧

### 新規（4）

| ファイル | 責務 |
|---------|------|
| `app/enrichers/narrative_transition.py` | 遷移検出 + 見通し集計 |
| `app/enrichers/source_reliability.py` | SRS 計算 + イベントへの適用 |
| `tests/test_narrative_transition.py` | 遷移テスト (16) |
| `tests/test_source_reliability.py` | SRS + 重み付きモメンタムテスト (17) |

### 変更（8）

| ファイル | 変更内容 |
|---------|---------|
| `app/database.py` | `narrative_transitions` テーブル + CRUD 2メソッド; `srs` カラムマイグレーション; `insert_enriched_event` に srs 追加 |
| `app/config.py` | `SourceReliabilityConfig` + `NarrativeTransitionConfig` 追加 |
| `configs/config.yaml` | `source_reliability:` + `narrative_transition:` セクション追加 |
| `app/enrichers/narrative_momentum.py` | `compute_weighted_category_momentum()` 関数追加 |
| `app/enrichers/narrative_graph.py` | `build_narrative_graph()` に SRS フィールド追加 |
| `app/reporter/daily_report.py` | `narrative_transitions` + `transition_outlook` パラメータ追加 |
| `app/reporter/templates/structural.md.j2` | 2新セクション + グラフ SRS 表示 |
| `app/__main__.py` | SRS適用・遷移検出・重み付きモメンタム・レポートパラメータ |

---

## 後方互換性

| 項目 | 結果 |
|------|------|
| 既存22セクション | 変更なし。新セクションを間に挿入 |
| `generate_structural_report()` | 新パラメータは全てデフォルト None |
| DB | CREATE IF NOT EXISTS + ALTER TABLE ADD COLUMN |
| Config | 全てデフォルト値あり。既存 YAML になくても動作 |
| SRS なし旧データ | `event.get("srs", 1.0)` で fallback |
| 新 enricher | 全て try/except 保護 |

---

## テスト結果

525 passed（490 既存 + 35 新規）
