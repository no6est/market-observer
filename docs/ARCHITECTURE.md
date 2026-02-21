# Architecture Design - PoC

## Pipeline Overview

```
[Collectors] → [Storage/SQLite] → [Detectors] → [Enrichers] → [Reporter]
     ↑                                                              ↓
  Hourly Job                                                  Daily Report (MD)
```

## Module Responsibilities

### 1. Collectors (`src/collectors/`)
外部ソースからデータを取得し、正規化してStorageに保存する。

| Collector | Source | Frequency | Output |
|-----------|--------|-----------|--------|
| `price.py` | yfinance | hourly | OHLCV per ticker |
| `rss.py` | RSS feeds (configurable) | hourly | Articles (title, summary, url, published) |
| `community.py` | Reddit, Hacker News | hourly | Posts (title, score, comments, url) |

- 共通: HTTP rate limit + exponential backoff (`utils/http_client.py`)
- 全rawデータをSQLiteに保存（audit trail）

### 2. Storage (`src/storage/`)
SQLiteベースのデータレイヤー。将来のDB差し替えを考慮した抽象化。

**Tables:**
- `price_data`: ticker, timestamp, open, high, low, close, volume
- `articles`: source, url, title, summary, published_at, collected_at
- `community_posts`: source, url, title, score, num_comments, collected_at
- `anomalies`: ticker, signal_type, score, detected_at, details (JSON)
- `themes`: name, keywords (JSON), first_seen, mention_count, momentum

### 3. Detectors (`src/detectors/`)
時系列データから特異点を検出する。

| Detector | Input | Method | Output |
|----------|-------|--------|--------|
| `price_anomaly.py` | price_data | Z-score (20日窓) | price change anomalies |
| `volume_anomaly.py` | price_data | Z-score (20日窓) | volume spike anomalies |
| `mention_anomaly.py` | articles + posts | Count delta vs MA | mention surge anomalies |

- **スコアリング**: 0.0-1.0 正規化スコア (σ値ベース)
- **クールダウン**: 同一ticker/signalは24h以内に再アラートしない
- **しきい値**: config で調整可能 (default: 2.0σ)

### 4. Enrichers (`src/enrichers/`)
検出された特異点にコンテキストを付与する。

| Enricher | Input | Output |
|----------|-------|--------|
| `theme_extractor.py` | articles + posts | テーマ/キーワード (TF-IDF) |
| `propagation.py` | anomalies + config | 波及候補 (銘柄関連マップ) |
| `hypothesis.py` | anomalies + articles | 仮説 (テンプレートベース) |

- テーマ抽出: TF-IDF で直近の新規キーワードを抽出、過去7日との差分で novelty を計算
- 波及候補: config に定義した銘柄グループ/セクターマップから関連銘柄を導出
- 仮説生成: テンプレートベース（PoC）。anomaly + 同時期のニュースを紐付け

### 5. Reporter (`src/reporter/`)
集約結果をMarkdownレポートに変換する。

- `daily_report.py`: 全セクションを含む日次レポート生成
- `templates/`: Jinja2テンプレート
- 出力先: `reports/YYYY-MM-DD_daily.md`

### 6. CLI Entrypoints
- `run_hourly`: Collectors → Storage (データ収集のみ)
- `run_daily`: Collectors → Storage → Detectors → Enrichers → Reporter

## Config (`configs/config.yaml`)
```yaml
tickers:
  - NVDA
  - MSFT
  - GOOGL
  - SNOW
  - CRWD
  - DDOG
  - PLTR
  - NET
  - MDB
  - PATH

rss_feeds:
  - name: TechCrunch
    url: https://techcrunch.com/feed/
  - name: Ars Technica
    url: https://feeds.arstechnica.com/arstechnica/index

reddit:
  subreddits:
    - wallstreetbets
    - stocks
    - technology

hackernews:
  enabled: true
  min_score: 10

detection:
  lookback_days: 20
  z_threshold: 2.0
  cooldown_hours: 24
  max_anomalies_per_report: 10

report:
  output_dir: reports
  top_n_anomalies: 5
  top_n_themes: 5

sector_map:
  AI_Infrastructure:
    - NVDA
    - GOOGL
    - MSFT
    - AMD
  Cloud_Security:
    - CRWD
    - PANW
    - ZS
  Data_Platform:
    - SNOW
    - DDOG
    - MDB
    - ESTC
```

## Implementation Plan

### Phase 1: Foundation (Task #3)
- Repository scaffold (directories, __init__.py, pyproject.toml)
- SQLite storage layer with models
- Config loader (YAML)
- HTTP client with rate limiting

### Phase 2: Parallel Implementation (Tasks #4, #5, #6)
- **Collectors**: price, RSS, community (independent)
- **Detectors + Enrichers**: anomaly scoring, theme extraction, hypothesis (depends on storage schema)
- **Reporter + CLI**: Markdown generation, CLI commands (depends on storage schema)

### Phase 3: Integration & Testing (Task #7)
- Unit tests for anomaly scoring & report rendering
- End-to-end test with mock data
- Sample report generation
