# 設計メモ: v9 ナラティブ・オブザバトリー v2

## 概要

v8「方向性対応市場応答」から v9「ナラティブ・オブザバトリー v2」への進化。
v8までのシステムは「単発イベント検出器」だったが、v9では**ナラティブの発生→拡散→ピーク→終息を時系列で追跡できる装置**に進化させる。

**目的**: ナラティブの「寿命」と「勢い」を構造的に観測可能にする。

**設計方針**: 既存の SIS/SPP/Early Drift/Regime 判定は中核として維持。3つの独立 Phase として拡張モジュールを追加し、日次レポートに8つの新セクションを挿入する。

---

## v8との差分: 何が新しいか

| 観点 | v8まで | v9 |
|------|--------|-----|
| ナラティブ追跡 | 日次スナップショットのみ | **narrative_tracks テーブルで日跨ぎ追跡** |
| ライフサイクル | 月次でカテゴリ盛衰を集計 | **日次で emerging/expanding/peak/cooling/inactive 判定** |
| モメンタム | なし | **日次カテゴリ別イベント増減率** |
| 冷却検出 | なし | **イベントなし日を意味ある観測に変換** |
| 初動シグナル | Early Drift（Strong条件のみ） | **+ Weak Drift（言及急増条件のみ）** |
| ナラティブグラフ | なし | **カテゴリ→銘柄ツリー（SIS強度付き）** |
| レジーム×ナラティブ | 月次のみ（Regime×Lag） | **日次でカテゴリ別クロス集計** |
| ストーリーサマリー | なし | **LLM/テンプレートによる当日要約** |

---

## Phase 構成

| Phase | 機能 | 依存 |
|-------|------|------|
| **Phase 1** | NarrativeTrack + Continuity + Lifecycle + Cooling | なし（既存enriched_eventsのみ） |
| **Phase 2** | Momentum + Weak Drift + Narrative Graph | なし（Phase 1と独立） |
| **Phase 3** | Regime×Narrative + Story Generator | なし（Phase 1出力あれば充実するが必須でない） |

各Phaseは独立して実装・テスト・マージ可能。

---

## 新規モジュール（5ファイル）

### narrative_track.py（Phase 1）

NarrativeTrack の中核モジュール。

**narrative_id 生成**:
```
category + "::" + md5(sorted_top5_keywords)[:12]
```

**照合ロジック**:
1. 当日 enriched_events を `narrative_category` でグループ化
2. 各グループから keywords 抽出（summary + evidence_titles からトークン化）
3. 既存 active tracks と照合:
   - **カテゴリ一致** が前提条件
   - **keyword Jaccard overlap** ≥ 0.5 → マッチ
   - 複合スコア = 0.6 × keyword_overlap + 0.4 × ticker_overlap
4. マッチ → 既存トラック更新（active_days++, peak_sis, avg_spp, sis_history 追記）
5. 不一致 → 新規トラック作成

**ライフサイクル判定**:

| ステータス | 条件 |
|-----------|------|
| emerging | active_days == 1 |
| expanding | active_days ≥ 2 かつ SISトレンド上昇 |
| peak | SIS がピーク付近（±10%）かつ SPP > 0.5 |
| cooling | 当日イベントなし かつ 前日まで active |
| inactive | 未出現 ≥ 3日（mark_tracks_inactive で一括更新） |

**冷却検出条件**: `previous_active_days ≥ 2` かつ `today_event_count == 0`

**sentence-transformers（オプション）**: キーワード Jaccard が 0.3〜0.6 の曖昧域にある場合のみ補助的に使用。未インストール時は完全にスキップ。dependencies には追加しない。

### narrative_momentum.py（Phase 2）

**モメンタム計算**:
```
momentum = (today_count - yesterday_count) / max(yesterday_count, 1)
```

| 値 | 分類 |
|----|------|
| yesterday=0 | 新出 |
| > 1.0 (100%) | 急拡大 |
| 0.3〜1.0 | 拡大中 |
| -0.3〜0.3 | 安定 |
| < -0.3 | 縮小 |

**弱い初動シグナル**:

| 条件 | Strong (Early Drift) | Weak (新規) |
|------|---------------------|-------------|
| カテゴリ比率 | < 20% | < 30% |
| z-score | ≥ 1.5 | ≥ 1.2 |
| 伝播パターン | SNS→Tier2 必須 | 不要 |
| 価格反応 | 未反応必須 | 不要 |
| 言及急増 | 明示条件なし | 必須 |

### narrative_graph.py（Phase 2）

enriched_events を narrative_category でグループ化し、各カテゴリ内のティッカーを SIS 順に表示。

strength: SIS ≥ 0.5 → strong, ≥ 0.2 → moderate, < 0.2 → weak

```
AI/LLM/自動化
├── NVDA (SIS: 0.85, strong)
├── AMD  (SIS: 0.45, moderate)
└── MSFT (SIS: 0.22, moderate)
```

### regime_narrative_cross.py（Phase 3）

現在のレジーム下で各カテゴリの event_count と avg_SIS をクロス集計。サンプル < 2件は「データ不足」と表示。

### story_generator.py（Phase 3）

1. LLM あり: Gemini プロンプトで 3-6行の観測ベース要約を生成
2. LLM なし: テンプレートフォールバック
   - 「本日は{dominant_cat}を中心に{event_count}件の構造変化を観測。{top_ticker}が{shock_type}で最大SIS {max_sis:.3f}。市場レジームは{regime}。」

---

## DB スキーマ: narrative_tracks

```sql
CREATE TABLE IF NOT EXISTS narrative_tracks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    narrative_id TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL,
    keywords TEXT,           -- JSON array
    primary_tickers TEXT,    -- JSON array
    start_date TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    active_days INTEGER NOT NULL DEFAULT 1,
    peak_sis REAL NOT NULL DEFAULT 0.0,
    avg_spp REAL NOT NULL DEFAULT 0.0,
    status TEXT NOT NULL DEFAULT 'emerging',
    sis_history TEXT,        -- JSON array
    metadata TEXT,           -- JSON
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

`CREATE TABLE IF NOT EXISTS` のため、既存DBへの移行は不要。初回実行時に自動作成。

Database クラスに追加したメソッド:
- `upsert_narrative_track(track)` — INSERT OR REPLACE
- `get_active_narrative_tracks(reference_date)` — status != 'inactive'
- `get_all_narrative_tracks()` — 全件
- `mark_tracks_inactive(reference_date, inactive_days=3)` — 未出現3日以上を inactive に

---

## Config 追加

```python
class NarrativeTrackConfig(BaseModel):
    keyword_overlap_threshold: float = 0.5
    ticker_overlap_threshold: float = 0.3
    cooling_inactive_days: int = 3
    weak_drift_z_threshold: float = 1.2
    weak_drift_category_ratio: float = 0.30
    use_embeddings: bool = False
```

全てデフォルト値あり。既存 YAML に `narrative_track:` なくても動作。

---

## 日次レポート構成（22セクション）

```
 1. 構造インパクトランキング           (既存)
 2. ストーリーサマリー                 (NEW Phase 3)
 3. ナラティブ分布                     (既存)
 4. ナラティブ継続性                   (NEW Phase 1)
 5. ナラティブライフサイクル           (NEW Phase 1)
 6. ナラティブモメンタム               (NEW Phase 2)
 7. 非AI構造変化ハイライト             (既存)
 8. 構造変化テーマ                     (既存)
 9. ナラティブグラフ                   (NEW Phase 2)
10. 因果チェーン                       (既存)
11. 仮説                               (既存)
12. 波及候補                           (既存)
13. 統計的ベースライン評価             (既存)
14. 市場レジーム                       (既存)
15. レジーム×ナラティブ分析           (NEW Phase 3)
16. メディア・エコーチェンバー評価     (既存)
17. ナラティブ健全性評価               (既存)
18. Early Drift（初動検出）            (既存)
19. 弱い初動シグナル                   (NEW Phase 2)
20. ナラティブ冷却                     (NEW Phase 1)
21. 構造変化である場合の問い           (既存)
22. 追跡クエリ                         (既存)
```

---

## __main__.py 統合ポイント

Phase 4（エンリッチメント）の末尾、SPP計算後・レポート生成前に挿入。

全て try/except で保護。失敗時は None/空リストでレポートに影響なし。

`generate_structural_report()` に新パラメータを追加（全てデフォルト None）。

---

## 変更ファイル一覧

### 新規ファイル（7）

| ファイル | Phase | 責務 |
|---------|-------|------|
| `app/enrichers/narrative_track.py` | 1 | NarrativeTrack構造体、照合、ライフサイクル、冷却 |
| `app/enrichers/narrative_momentum.py` | 2 | モメンタム計算 + 弱い初動検出 |
| `app/enrichers/narrative_graph.py` | 2 | テーマ→銘柄グラフ構築 |
| `app/enrichers/regime_narrative_cross.py` | 3 | レジーム×ナラティブ交差分析 |
| `app/enrichers/story_generator.py` | 3 | LLM/テンプレートベースのストーリーサマリー |
| `tests/test_narrative_track.py` | 1 | Phase 1テスト（24テスト） |
| `tests/test_narrative_v2.py` | 2-3 | Phase 2-3テスト（34テスト） |

### 変更ファイル（7）

| ファイル | 変更内容 |
|---------|---------|
| `app/database.py` | `narrative_tracks` テーブル追加 + 4 CRUD メソッド |
| `app/config.py` | `NarrativeTrackConfig` モデル追加 |
| `configs/config.yaml` | `narrative_track:` セクション追加 |
| `app/__main__.py` | run_daily() に Phase 1-3 enricher 呼び出し追加 |
| `app/reporter/daily_report.py` | `generate_structural_report()` に6新パラメータ追加 |
| `app/reporter/templates/structural.md.j2` | 8つの新セクション追加 |
| `.github/workflows/pipeline.yml` | 当日レポートのみ成果物化 |

---

## Pipeline 変更

GitHub Actions の `pipeline.yml` を更新:

- `REPORT_DATE` を明示的にセット（`date -u +%Y-%m-%d`）
- `--date` オプションで日付を渡す
- `_output/` に当日生成分のみコピーして成果物にアップロード
  - daily → `{date}_structural.md`
  - weekly → `{date}_weekly.md` + チャート画像
  - monthly → `{date}_monthly.md` + ラグヒストグラム
- 成果物名を `report-{pipeline}-{date}` に変更

---

## 後方互換性

| 項目 | 結果 |
|------|------|
| 既存テンプレートセクション | 一切変更なし。新セクションを既存の間に挿入 |
| `generate_structural_report()` | 新パラメータは全てデフォルト None |
| DB | CREATE IF NOT EXISTS。既存テーブル変更なし。移行不要 |
| Config | 全てデフォルト値あり。既存 YAML になくても動作 |
| 新enricher | 全て try/except 保護。失敗時は空データでレポート生成 |
| 週次・月次レポート | 影響なし |

---

## テスト

| テストファイル | テスト数 | 対象 |
|-------------|---------|------|
| `test_narrative_track.py` | 24 | narrative_id生成、Jaccard、照合、ライフサイクル、冷却、DB統合 |
| `test_narrative_v2.py` | 34 | モメンタム、弱ドリフト、グラフ、レジーム×ナラティブ、ストーリー |
| **合計** | **58** (テストファイル全体: 490) | |

---

## 既知の制約

### 初回実行時

初回実行では narrative_tracks テーブルが空のため、全トラックが「新出(emerging)」となる。2日目以降から継続性・拡大・冷却の検出が有効になる。

### キーワード抽出の品質

現在の keyword 抽出は単純なトークン化 + ストップワード除去。日本語テキストのトークン化は未対応。英語テキスト（RSS、Reddit）からの抽出が中心となる。

### sentence-transformers

オプション依存。未インストール時は Jaccard 類似度のみで照合する。曖昧域（0.3〜0.6）での精度がやや低下するが、実用上は問題ない。

---

*ドキュメント更新日: 2026-03-07 (v9)*
