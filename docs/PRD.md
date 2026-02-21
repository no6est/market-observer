# Market Observability System - PRD

## 1. Overview

社内向け「構造観察」システム。市場の特異点を検出し、関連コンテキストを自動収集し、テーマの出現・変質・波及の仮説を提示する。投資判断・助言は一切行わない。

## 2. Users & Use Cases

### Primary Users
- 社内リサーチチーム：日次レポートで市場構造の変化を把握
- プロダクトチーム：競合・隣接領域の動向を早期に検知

### Use Cases
1. **朝のキャッチアップ**: 日次レポートで前日の特異点とテーマ変化を5分で把握
2. **深掘り調査**: 特異点から関連銘柄・ニュース・口コミを辿り、構造的な変化を理解
3. **テーマ追跡**: 「AI Infrastructure」「SaaS Consolidation」等のテーマの勢い変化を継続監視
4. **波及予測**: ある銘柄/テーマの変動が隣接領域に波及する兆候を事前に把握

## 3. Output Specification

### Daily Report (Markdown)
```
# Market Observability Report - 2025-02-21

## Top Anomalies
| Rank | Ticker | Signal      | Score | Summary          |
|------|--------|-------------|-------|------------------|
| 1    | SNOW   | Volume 4.2σ | 0.92  | 出来高が通常の4.2倍... |

## Emerging Themes
- **AI Agent Infrastructure** (novelty: high, momentum: rising)
  - 関連: CRWD, PANW, DDOG
  - 初出: 2日前、言及数: 47 → 128

## Facts (何が起きたか)
- SNOW: 終値 $182.40 (+8.3%), 出来高 12.4M (平均比 4.2x)
- Source: [Yahoo Finance](...)

## Hypotheses (なぜ起きたか)
- [確信度: 0.7] Snowflakeの決算発表でAIデータパイプライン需要...
  - 根拠: [Earnings Call Transcript](...)
  - 反論: 市場全体のリスクオン相場の影響も

## Propagation Candidates (波及候補)
- データインフラ: DBT, Fivetran (非上場), DDOG
- 競合: GOOG BigQuery, AMZN Redshift

## Tracking Queries (追跡クエリ)
- "snowflake AI pipeline" site:reddit.com
- "data infrastructure earnings" since:2025-02-20
```

## 4. Non-Functional Requirements

| 項目 | 要件 |
|------|------|
| 更新頻度 | hourly (軽量収集) + daily (集約レポート) |
| レイテンシ | hourly < 5分、daily < 15分 |
| 対象銘柄 | PoC: 米国AI/SaaS 10-20銘柄 |
| データソース | 株価API (無料) + RSS 3-5件 + Reddit/HN |
| 保存先 | SQLite (PoC) → BigQuery (将来) |
| 可用性 | ローカル実行で十分 (PoC) |
| セキュリティ | APIキーは環境変数/config、レポートは社内限定 |

## 5. Evaluation Metrics

| 指標 | 目標 |
|------|------|
| アラート納得度 | Top5のうち3件以上が「確かに重要」と感じる |
| 過剰アラート率 | ノイズ < 30% |
| テーマ検出速度 | 主要メディア報道の同日〜1日前にキーワード検出 |
| 仮説の質 | 根拠リンクが有効、かつ反論も記載されている |
| レポート生成成功率 | 95%以上 (クラッシュなし) |

## 6. Out of Scope
- 自動売買・投資助言・推奨銘柄提示
- 完璧な因果推論
- SNS全量収集
- リアルタイムアラート (PoC)
- モバイルUI
