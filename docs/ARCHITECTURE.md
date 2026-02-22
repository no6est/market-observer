# Market Observability System - Architecture

> 最終更新: v7 (2026-02-22)

---

## 1. システム概要

市場の構造変化を**検出→文脈付与→可視化**する観測システム。
投資助言ではなく、「何が起きていて、それがどう広がり、市場がどう応答したか」を理解するためのツール。

### パイプライン全体像

```
                          ┌─────────────┐
                          │  External   │
                          │   Sources   │
                          │ yfinance    │
                          │ RSS feeds   │
                          │ Reddit/HN   │
                          └──────┬──────┘
                                 │
                    ┌────────────▼────────────┐
                    │     Collectors          │  ← run_hourly / run_daily
                    │  price, rss, community  │
                    └────────────┬────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │     SQLite Database     │
                    │  price_data, articles,  │
                    │  community_posts, ...   │
                    └────────────┬────────────┘
                                 │
              ┌──────────────────┼──────────────────┐
              │                  │                   │
   ┌──────────▼──────┐  ┌───────▼───────┐  ┌───────▼───────┐
   │   run_daily     │  │  run_weekly   │  │  run_monthly  │
   │                 │  │               │  │               │
   │ Detect          │  │ 7日集約       │  │ 30日集約      │
   │ → Enrich        │  │ 仮説評価      │  │ ライフサイクル │
   │ → Report        │  │ トレンド分析  │  │ 市場応答構造   │
   └────────┬────────┘  └───────┬───────┘  └───────┬───────┘
            │                   │                   │
            ▼                   ▼                   ▼
     _structural.md       _weekly.md          _monthly.md
     + charts (PNG)       + charts (PNG)      + charts (PNG)
```

### 4つの実行モード

| コマンド | 頻度 | 目的 | 出力 |
|---------|------|------|------|
| `run_hourly` | 毎時 | データ収集のみ | DB蓄積 |
| `run_daily` | 毎日 | 異常検出→エンリッチ→レポート | `_structural.md` |
| `run_weekly` | 毎週 | 7日メタ分析→仮説評価→チャート | `_weekly.md` + PNG |
| `run_monthly` | 毎月 | 30日ライフサイクル→市場応答構造 | `_monthly.md` + PNG |

各コマンドは**独立実行可能**（他コマンドの事前実行は不要）。

---

## 2. ディレクトリ構成

```
app/
├── __main__.py              # CLI エントリポイント (4コマンド)
├── config.py                # Pydantic 設定モデル
├── database.py              # SQLite ストレージ層
├── models.py                # データモデル (PriceData, Article, CommunityPost)
│
├── collectors/              # 外部データ収集 (3モジュール)
│   ├── price.py             #   yfinance OHLCV
│   ├── rss.py               #   RSS フィード
│   └── community.py         #   Reddit + HackerNews
│
├── detectors/               # 異常検出 (4モジュール)
│   ├── price_anomaly.py     #   価格変動 Z-score
│   ├── volume_anomaly.py    #   出来高スパイク
│   ├── mention_anomaly.py   #   言及急増
│   └── combined.py          #   複合スコアリング
│
├── enrichers/               # 文脈付与・分析 (25モジュール)
│   ├── [分類系]             #   shock_classifier, narrative_classifier
│   ├── [スコアリング系]     #   impact_scorer, evidence_scorer, spp, ai_centricity
│   ├── [構造分析系]         #   propagation, media_tier, echo_chamber, regime_detector
│   ├── [ナラティブ系]       #   narrative_*, theme_extractor, non_ai_highlights
│   ├── [仮説・検証系]       #   hypothesis, causal_chain, self_verification
│   ├── [集約分析系]         #   weekly_analysis, monthly_analysis, market_response
│   └── [チャート]           #   narrative_chart
│
├── reporter/                # レポート生成
│   ├── daily_report.py      #   Jinja2 レンダリング
│   └── templates/           #   4テンプレート (.md.j2)
│
├── llm/                     # LLM連携
│   └── gemini.py            #   Google Gemini API クライアント
│
└── utils/
    └── http_client.py       # HTTP ユーティリティ

scripts/
└── backfill_daily.py        # 過去日付バックフィル

tests/                       # 398テスト
configs/
└── config.yaml              # 全設定
reports/                     # 生成レポート出力先
data/
└── market_obs.db            # SQLite DB (.gitignore)
```

---

## 3. データベース設計

### テーブル一覧

```
┌─────────────────┐     ┌─────────────────┐     ┌──────────────────┐
│   price_data    │     │    articles      │     │ community_posts  │
│ ─────────────── │     │ ─────────────── │     │ ──────────────── │
│ ticker          │     │ source          │     │ source           │
│ timestamp       │     │ url (UNIQUE)    │     │ url (UNIQUE)     │
│ open/high/low   │     │ title           │     │ title/body       │
│ close/volume    │     │ summary         │     │ score/comments   │
│ collected_at    │     │ published_at    │     │ author           │
└────────┬────────┘     └────────┬────────┘     └────────┬─────────┘
         │ 収集層                │                        │
─────────┼───────────────────────┼────────────────────────┼──────────
         │ 検出層                │                        │
┌────────▼────────┐              │                        │
│   anomalies     │              │                        │
│ ─────────────── │              │                        │
│ ticker          │              │                        │
│ signal_type     │              │                        │
│ score/z_score   │              │                        │
│ summary/details │              │                        │
└────────┬────────┘              │                        │
         │ エンリッチ層          │                        │
┌────────▼──────────────────────────────────────────────────────────┐
│                        enriched_events                            │
│ ──────────────────────────────────────────────────────────────── │
│ date, ticker, signal_type (UNIQUE制約)                           │
│ shock_type, sis, narrative_category, ai_centricity               │
│ summary, evidence_score, market/media/official_evidence          │
│ tier1_count, tier2_count, sns_count, diffusion_pattern           │
│ spp (構造持続確率)                                                │
└──────────────────────────────────────────────────────────────────┘

┌────────────────────┐  ┌────────────────────┐  ┌────────────────────┐
│ narrative_snapshots │  │  regime_snapshots   │  │  hypothesis_logs   │
│ ────────────────── │  │ ────────────────── │  │ ────────────────── │
│ date, category     │  │ date, regime       │  │ date, ticker       │
│ event_count        │  │ avg_volatility     │  │ hypothesis         │
│ event_pct          │  │ declining_pct      │  │ evidence/confidence│
│ total_events       │  │ regime_confidence  │  │ status (※)         │
└────────────────────┘  │ spp_weights (JSON) │  │ evaluation_result  │
                        └────────────────────┘  └────────────────────┘

┌────────────────────┐  ┌────────────────────┐
│      themes        │  │ reaction_patterns  │
│ ────────────────── │  │ ────────────────── │
│ name, keywords     │  │ date, ticker       │
│ first_seen         │  │ sector, shock_type │
│ mention_count      │  │ price_direction    │
│ momentum           │  │ price_change_pct   │
└────────────────────┘  └────────────────────┘

※ hypothesis_logs.status: pending / confirmed / expired / drift_pending
```

### 主要インデックス

| インデックス | 対象 | 用途 |
|-------------|------|------|
| idx_price_ticker_ts | price_data(ticker, timestamp) | 銘柄×日付の高速検索 |
| idx_enriched_events_date | enriched_events(date) | 日付範囲クエリ |
| idx_narrative_snapshots_date | narrative_snapshots(date) | ナラティブ履歴参照 |
| idx_regime_snapshots_date | regime_snapshots(date) | レジーム履歴参照 |
| idx_hypothesis_logs_status | hypothesis_logs(status) | drift_pending フィルタ |

---

## 4. Enricher モジュール詳細

25モジュールを機能別に分類。

### 4.1 分類系

| モジュール | 入力 | 出力 | 説明 |
|-----------|------|------|------|
| `shock_classifier` | anomaly, articles, posts | 5種ショックタイプ | テクノロジー/ビジネスモデル/規制/ナラティブシフト/業績シグナル |
| `narrative_classifier` | anomaly, articles, posts | 8カテゴリ | AI・エネルギー・金融・規制・半導体・ガバナンス・社会・その他 |

### 4.2 スコアリング系

| モジュール | 出力 | スケール | 説明 |
|-----------|------|---------|------|
| `impact_scorer` | SIS (Structure Impact Score) | 0.0-1.0 | カバレッジ幅×公式ソース×競合関与 |
| `evidence_scorer` | evidence_score | 0.0-1.0 | 市場+メディア+公式ソースの複合信頼度 |
| `spp` | SPP (Structural Persistence Probability) | 0.0-1.0 | 一過性 vs 構造変化の判別確率 |
| `ai_centricity` | ai_centricity | 0.0-1.0 | AIキーワード集中度 |

**SPP の5要素**:
```
SPP = consecutive_days (0.25) + evidence_trend (0.20) + price_trend (0.20)
    + media_diffusion (0.20) + sector_propagation (0.15)
```

### 4.3 構造分析系

| モジュール | 説明 |
|-----------|------|
| `propagation` | セクターマップからの波及候補検出 + 方向推定（positive/negative/mixed） |
| `media_tier` | Tier1(主要通信社)/Tier2(専門メディア)/SNS の伝播パターン分類 |
| `echo_chamber` | メディアエコーの検出と evidence_score への補正係数適用 |
| `regime_detector` | 3レジーム判定（normal/high_vol/tightening）+ レジーム適応SPP重み |

### 4.4 ナラティブ分析系

| モジュール | 説明 |
|-----------|------|
| `narrative_concentration` | カテゴリ分布の偏り検出（7日移動平均ベース） |
| `narrative_overheat` | AI集中の過熱警告（中央値evidence + 7日デルタ） |
| `narrative_baseline` | カテゴリ別統計ベースライン（7/30/90日窓） |
| `non_ai_highlights` | 高SIS+低メディア+市場裏付けの「見落とされている」非AIイベント |
| `theme_extractor` | TF-IDF キーワード + novelty スコアリング |
| `ticker_aliases` | 企業名⇔ティッカーのエイリアスマッチング |

### 4.5 仮説・検証系

| モジュール | 説明 |
|-----------|------|
| `hypothesis` | テンプレートベースの仮説生成（anomaly + 同時期ニュースの紐付け） |
| `causal_chain` | trigger → direct impact → structural implication のチェーン構築 |
| `structural_questions` | レポートごとに3つの前向き質問を生成 |
| `narrative_archive` | 仮説の30日後事後評価（confirmed/expired/inconclusive） |
| `self_verification` | 過熱アラートの予測ログと事後検証（TP/FP/TN/FN） |

### 4.6 集約分析系

| モジュール | 時間軸 | 主要セクション |
|-----------|--------|--------------|
| `weekly_analysis` | 7日 | ナラティブトレンド、伝播構造、仮説評価 |
| `monthly_analysis` | 30日 | ライフサイクル(8セクション) + 市場応答構造(5セクション) |
| `market_response` | 30日 | 反応ラグ、ウォッチ評価、再編連鎖、Drift追跡、応答プロファイル |

### 4.7 チャート

| モジュール | 生成物 |
|-----------|--------|
| `narrative_chart` | ナラティブトレンド折れ線 / メディア伝播棒グラフ / 反応ラグヒストグラム |

---

## 5. 月次レポート構成（13セクション）

セクション1-8は v6、セクション9-13は v7 で追加。

```
┌─────────────────────────────────────────────────────────────────┐
│                    月次レポート (monthly.md)                      │
│                                                                  │
│  [v6: ナラティブ観測]                                            │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ 1. ナラティブ・ライフサイクル  ← 30日のカテゴリ盛衰    │    │
│  │ 2. 仮説レトロスペクティブ      ← 30日前の仮説の事後評価 │    │
│  │ 3. 市場レジーム推移            ← 遷移回数・安定度       │    │
│  │ 4. 構造的持続性                ← コア vs 一時的銘柄     │    │
│  │ 5. 前月比較                    ← ナラティブ/銘柄の差分  │    │
│  │ 6. ショック・伝播構造          ← ショック種別×伝播集計  │    │
│  │ 7. 来月の注目ポイント          ← ウォッチ銘柄+見通し   │    │
│  │ 8. 月間ナラティブ推移          ← 日次カテゴリ分布一覧  │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                  │
│  [v7: 市場応答構造]                                              │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  9. 反応ラグ         ← ナラティブ後、何日で価格反応？  │    │
│  │ 10. ウォッチ評価     ← 前月注目銘柄のフォローアップ    │    │
│  │ 11. 再編連鎖         ← 消滅カテゴリ→台頭カテゴリ検出  │    │
│  │ 12. Early Drift      ← SNS初動→メディア到達の追跡     │    │
│  │ 13. 応答プロファイル ← 即時/遅延/過熱/無反応/再編 分類 │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

### セクション間の依存関係

```
PHASE 1 (反応ラグ) ───→ PHASE 5 (応答プロファイル)
PHASE 3 (再編連鎖) ───→ PHASE 5 (再編型分類)
PHASE 2 (ウォッチ)  ← 独立
PHASE 4 (Drift)    ← 独立（run_weekly の蓄積が前提）
```

---

## 6. 日次パイプライン詳細

`run_daily` は5フェーズで構成。

### Phase 1: 収集

```
yfinance (period=1mo)  ──→ price_data
RSS feeds (6 sources)  ──→ articles
Reddit (5 subreddits)  ──→ community_posts
HackerNews (top 100)   ──→ community_posts
```

### Phase 2: 検出

```
price_data ──→ price_anomaly (Z-score, 20日窓)  ──┐
price_data ──→ volume_anomaly (leave-one-out)    ──┤──→ combined (加重: 0.4/0.3/0.3)
articles   ──→ mention_anomaly (MA比較)          ──┘     → anomalies テーブル
```

### Phase 3: 構造エンリッチ

```
anomalies ──→ shock_classifier     → shock_type (5種)
          ──→ impact_scorer        → SIS (0-1)
          ──→ narrative_classifier → narrative_category (8種)
          ──→ propagation          → propagation_targets
          ──→ evidence_scorer      → evidence_score
          ──→ media_tier           → diffusion_pattern
          ──→ ai_centricity        → ai_centricity
          ──→ spp                  → SPP (0-1)
                                     → enriched_events テーブル
```

### Phase 4: 高度分析

```
enriched_events ──→ theme_extractor        → themes テーブル
                ──→ hypothesis             → hypothesis_logs テーブル
                ──→ causal_chain           → テンプレート変数
                ──→ narrative_concentration → ナラティブ指標
                ──→ narrative_overheat     → 過熱アラート
                ──→ regime_detector        → regime_snapshots テーブル
                ──→ echo_chamber           → evidence補正
                ──→ narrative_baseline     → baseline評価
                ──→ self_verification      → 予測ログ
                ──→ early_drift検出        → テンプレート変数
```

### Phase 5: レポート生成

```
全変数 ──→ Jinja2 (structural.md.j2) ──→ reports/{date}_structural.md
```

---

## 7. 主要スコアの関係

```
                    ┌──────────────┐
                    │  anomaly     │
                    │  score (0-1) │  ← 検出時のシグナル強度
                    └──────┬───────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
     ┌────────────┐ ┌───────────┐ ┌───────────┐
     │ SIS (0-1)  │ │ evidence  │ │ SPP (0-1) │
     │ 構造的影響 │ │ score     │ │ 持続確率  │
     │ 度         │ │ (0-1)     │ │           │
     └────────────┘ │ 証拠信頼度│ └───────────┘
                    └───────────┘
                           │
                    ┌──────▼───────┐
                    │ ai_centricity│  ← AI集中度による過熱判定
                    │ (0-1)        │
                    └──────────────┘
```

| スコア | 高い = | 低い = |
|--------|--------|--------|
| anomaly score | シグナルが統計的に異常 | 通常範囲 |
| SIS | 構造的に影響が大きい | 一過性 |
| evidence_score | 複数ソースで裏付けあり | 単一ソースのみ |
| SPP | 構造変化の可能性が高い | 一過性ノイズ |
| ai_centricity | AIトピックに集中 | 多様なトピック |

---

## 8. 設定ファイル構成

`configs/config.yaml` の全設定項目。

### 銘柄・データソース

| 設定 | 内容 | 件数 |
|------|------|------|
| `tickers` | 監視対象銘柄 | 15 (AI 10 + 非AI 5) |
| `rss_feeds` | RSSフィード | 6 (TechCrunch, ArsTechnica, TheVerge, Reuters, CNBC, MarketWatch) |
| `reddit.subreddits` | Redditサブレディット | 5 (wallstreetbets, stocks, technology, investing, energy) |
| `hackernews` | HackerNews設定 | min_score: 10, limit: 100 |
| `sector_map` | セクター→銘柄マッピング | 8セクター (AI_Infrastructure等) |

### 検出・分析パラメータ

| 設定 | デフォルト | 説明 |
|------|-----------|------|
| `detection.z_threshold` | 2.0 | 異常検出のZ-score閾値 |
| `detection.lookback_days` | 20 | Z-score計算の窓サイズ |
| `detection.cooldown_hours` | 24 | 同一シグナルの再アラート抑制 |
| `narrative.ai_threshold` | 0.3 | AI集中度の閾値 |
| `narrative.overheat_ai_pct` | 0.5 | 過熱警告のAI比率閾値 |
| `regime.vol_threshold` | 0.25 | 高ボラティリティ判定閾値 |
| `regime.declining_threshold` | 0.50 | 引き締めレジーム判定閾値 |
| `baseline.windows` | [7, 30, 90] | 統計ベースラインの窓サイズ |

---

## 9. テスト構成

**398テスト** (pytest)

| カテゴリ | テスト数 | 対象 |
|---------|---------|------|
| Detectors | ~30 | price/volume/mention/combined anomaly |
| Enrichers (v1-v5) | ~250 | 各enricherモジュールの単体テスト |
| Monthly Analysis (v6) | 24 | ライフサイクル、レジーム弧、前月比較 |
| Market Response (v7) | 30 | 反応ラグ、ウォッチ評価、再編連鎖、応答プロファイル |
| Reporter/Config/Storage | ~60 | テンプレートレンダリング、DB操作、設定ロード |

---

## 10. バージョン進化

| Version | 名称 | 追加内容 |
|---------|------|---------|
| v1 | 基盤 | Collectors + Detectors + 基本Reporter |
| v2 | ナラティブ信頼性 | shock_classifier, impact_scorer, evidence_scorer, media_tier |
| v3 | 自己検証 | self_verification, narrative_archive, echo_chamber |
| v4 | 統計ベースライン | narrative_baseline, regime_detector, spp |
| v5 | 週次品質 | weekly_analysis, narrative_chart, SPP重複排除 |
| v6 | 月次ナラティブ | monthly_analysis (セクション1-8), monthly.md.j2 |
| v7 | 市場応答構造 | market_response (セクション9-13), reaction_lag chart, spp reference_date修正 |

### 各バージョンの設計ドキュメント

| ファイル | 内容 |
|---------|------|
| `docs/PRD.md` | プロダクト要件定義 |
| `docs/design_v2_narrative_reliability.md` | v2 ナラティブ信頼性設計 |
| `docs/design_v3_self_verification.md` | v3 自己検証設計 |
| `docs/design_v4_statistical_baseline.md` | v4 統計ベースライン設計 |
| `docs/design_v5_weekly_quality.md` | v5 週次品質改善設計 |
| `docs/design_v6_monthly_narrative.md` | v6 月次ナラティブ設計 |
| `docs/design_v7_market_response.md` | v7 市場応答構造設計 |
