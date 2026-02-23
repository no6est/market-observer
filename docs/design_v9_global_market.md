# 設計メモ: v9 GLOBAL マルチマーケット対応

## 概要

v8「方向性対応市場応答」から v9「GLOBAL マルチマーケット対応」への進化。
v8までは US 市場15銘柄のみを対象としていたが、
v9では**日本市場10銘柄を加えた25銘柄の横断分析と日米比較分析**を実現。

**目的**: 単一市場のナラティブ観測から、クロスマーケットの構造変化伝播の観測へ拡張。

**設計方針**: 既存のUS分析を非破壊のまま、`market_scope` 設定により GLOBAL モードを有効化。月次レポートにセクション17-19（日米比較）を新設。Gemini LLM の思考モデル対応（`thinkingBudget`）と仮説出力の構造化を同時に実施。

---

## v8との差分: 何が新しいか

| 観点 | v8（方向性対応市場応答） | v9（GLOBAL マルチマーケット） |
|------|------------------------|------------------------------|
| 対象市場 | US のみ（15銘柄） | **US 15 + JP 10 = 25銘柄** |
| セクターマップ | 8セクター（US） | **+ 6 JP セクター（計14）** |
| RSS ソース | 6フィード（英語） | **+ 4 JP フィード（計10）** |
| レジーム検出 | 全銘柄一括 | **+ 市場別レジーム（US/JP個別）** |
| 月次レポート | 16セクション | **19セクション（+ 日米比較3セクション）** |
| 銘柄ラベル | ティッカーのみ | **[US]/[JP] プレフィックス + 日本語社名** |
| LLM出力 | 1テキスト | **タイトル + 本文の構造化出力** |
| LLM思考制御 | なし | **`thinkingBudget: 0` で出力切れ防止** |
| バックフィル | US銘柄のみ | **`active_tickers` で全銘柄対応** |

---

## 設定モデル拡張

### `market_scope` プロパティ

`configs/config.yaml` に `market_scope` フィールドを追加:

```yaml
market_scope: US        # US のみ（デフォルト）
market_scope: GLOBAL    # US + JP
```

### `config.py` の新プロパティ

| プロパティ | `US` モード | `GLOBAL` モード |
|-----------|-------------|----------------|
| `active_tickers` | `tickers` (15) | `tickers` + `jp_tickers` (25) |
| `active_rss_feeds` | `rss_feeds` (6) | `rss_feeds` + `jp_rss_feeds` (10) |
| `active_sector_map` | `sector_map` (8) | `sector_map` + `jp_sector_map` (14) |
| `is_global` | `False` | `True` |

既存の `tickers`, `sector_map` 等はそのまま残り、`active_*` プロパティが実行時に適切な結合を返す。

### JP銘柄・セクター

```yaml
jp_tickers:
  - 7203.T   # トヨタ
  - 6758.T   # ソニー
  - 9984.T   # SoftBank Group
  - 8035.T   # 東京エレクトロン
  - 9432.T   # NTT
  - 6098.T   # リクルート
  - 6861.T   # キーエンス
  - 6501.T   # 日立
  - 8306.T   # 三菱UFJ
  - 2914.T   # JT

jp_sector_map:
  JP_Manufacturing: [7203.T, 6501.T]
  JP_Tech: [6758.T, 8035.T, 6861.T]
  JP_Finance: [8306.T]
  JP_Telecom: [9432.T]
  JP_Services: [6098.T, 9984.T]
  JP_Consumer: [2914.T]
```

---

## JP銘柄サポートの設計

### ティッカーエイリアス (`ticker_aliases.py`)

JP銘柄の企業名⇔ティッカー変換テーブルを追加:

```python
JP_ALIASES = {
    "7203.T": ["トヨタ", "Toyota", "TOYOTA"],
    "6758.T": ["ソニー", "Sony", "SONY"],
    "9984.T": ["ソフトバンク", "SoftBank"],
    ...
}
```

RSS記事・コミュニティ投稿からのJP銘柄関連コンテンツ検出に使用。

### 市場分類ユーティリティ (`utils/market_utils.py`)

```python
def is_jp_ticker(ticker: str) -> bool
def get_market_label(ticker: str) -> str      # "[US]" or "[JP]"
def get_jp_name(ticker: str) -> str | None    # "トヨタ", "ソニー" etc.
def format_ticker_display(ticker: str) -> str  # "7203.T（トヨタ）"
```

テンプレート表示とレポート全体で統一的に使用。

### 市場別レジーム検出

`regime_detector.py` を拡張し、全体・US・JPの3レジームを同時計算:

```python
# regime_info に追加
{
    "regime": "tightening",          # 全体
    "us_regime": "tightening",       # US銘柄のみ
    "jp_regime": "high_vol",         # JP銘柄のみ
    "us_volatility": 0.536,
    "jp_volatility": 0.434,
    "us_declining_pct": 0.667,
    "jp_declining_pct": 0.400,
}
```

---

## レポート構成（19セクション）

月次レポートにセクション17-19を新設。

| # | セクション | 由来 | 読み手が得る答え |
|---|-----------|------|----------------|
| 1-16 | v6-v8 と同一 | v6-v8 | （変更なし） |
| **17** | **日米ナラティブ比較** | **v9** | **USとJPでナラティブの偏りはどう違うか？** |
| **18** | **日米反応速度比較** | **v9** | **USとJPで市場の反応速度は異なるか？** |
| **19** | **ナラティブ移植候補** | **v9** | **USで急騰したテーマが3日以内にJPに波及したか？** |

### セクション17: 日米ナラティブ比較

USとJPのナラティブカテゴリ比率を月間平均で比較。差分が10pt以上のカテゴリに★マーク。

```
| カテゴリ | US比率 | JP比率 | 差分(pt) | 注目 |
|----------|--------|--------|----------|------|
| AI/LLM/自動化 | 77% | 21% | +55 | ★ |
```

### セクション18: 日米反応速度比較

US/JPそれぞれの反応ラグ統計を比較。即時反応率と未反応率の差が市場特性を反映。

```
| 指標 | US | JP |
|------|-----|-----|
| 平均反応ラグ | 2.1日 | 2.1日 |
| 即時反応率 | 38% | 21% |
| 未反応率 | 27% | 36% |
```

### セクション19: ナラティブ移植候補

USでカテゴリ比率が前日比+20pt以上急騰した場合、3日以内にJPで同カテゴリが+10pt以上増加したケースを検出。

**設計意図**: グローバルなナラティブがJP市場にどの程度の遅延で伝播するかを可視化。

---

## Gemini LLM 思考モデル対応

### 問題: 出力トークン切れ

`gemini-3-flash-preview` は**思考モデル**であり、`maxOutputTokens` が思考トークンと出力トークンの合計に適用される。思考に~400-500トークンを消費するため、`maxOutputTokens=300` では出力が途中で切れる。

```
# 問題の実例
promptTokenCount: 141
candidatesTokenCount: 15    ← 実出力わずか15トークン
thoughtsTokenCount: 448     ← 思考に448トークン消費
totalTokenCount: 604
finishReason: MAX_TOKENS    ← トークン枯渇
```

### 解決: `thinkingBudget: 0`

構造化出力タスク（仮説強化、センチメント分類、ナラティブ分類、テーマ名生成）では思考が不要なため、`thinkingBudget: 0` で無効化。

```python
def generate(self, prompt, max_tokens=1024, thinking_budget=None):
    gen_config = {"maxOutputTokens": max_tokens, "temperature": 0.3}
    if thinking_budget is not None:
        gen_config["thinkingConfig"] = {"thinkingBudget": thinking_budget}
```

### 適用箇所

| メソッド / 呼び出し元 | 用途 | thinking_budget |
|-----------------------|------|----------------|
| `summarize_anomaly_ja` | 異常サマリー生成 | 0 |
| `enhance_hypothesis_ja` | 仮説タイトル+本文 | 0 |
| `generate_theme_name_ja` | テーマ名生成 | 0 |
| `market_response._classify_sentiment_batch` | センチメント分類 | 0 |
| `narrative_classifier` Gemini フォールバック | ナラティブ分類 | 0 |
| `monthly_analysis` LLM呼び出し | 月次分析 | デフォルト（思考有効） |

---

## 仮説出力の構造化

### 問題

LLM強化後の仮説テキスト全体がMarkdown見出し行 (`### 1. {text}`) に挿入されるため、複数文の出力や途中切れがレンダリングを壊していた。

### 解決: タイトル/本文分離

`enhance_hypothesis_ja` の出力を構造化:

```python
# LLMプロンプト
"タイトル: （25文字以内の短い見出し。末尾に句点不要）"
"本文: （2-3文の説明）"

# 戻り値: dict
{"title": "エヌビディアへの言及急増", "body": "NVDAに関する言及数が..."}
```

テンプレートでの表示:
```jinja2
### {{ loop.index }}. {{ h.hypothesis }}      ← タイトル（見出し）
{% if h.hypothesis_body %}
{{ h.hypothesis_body }}                        ← 本文（段落）
{% endif %}
```

`_parse_title_body` パーサーは以下を処理:
- 半角/全角コロンの両方に対応
- 本文の複数行継続
- タイトル後のラベルなしテキストを本文として解釈

---

## バックフィル GLOBAL 対応

`scripts/backfill_daily.py` の2箇所を修正:

| 行 | 修正前 | 修正後 | 効果 |
|----|--------|--------|------|
| L351 | `cfg.tickers` | `cfg.active_tickers` | JP銘柄も検出対象に |
| L365 | `cfg.sector_map` | `cfg.active_sector_map` | JP セクターで波及分析 |

`active_tickers` / `active_sector_map` は `market_scope` に応じてUS-only or GLOBAL を返す。

---

## 変更ファイル一覧

| ファイル | 変更種別 | 内容 |
|---------|---------|------|
| `app/config.py` | 修正 | `market_scope`, `active_tickers`, `active_sector_map`, `active_rss_feeds`, `is_global` プロパティ |
| `app/__main__.py` | 修正 | `active_tickers`, `active_rss_feeds`, `active_sector_map` 使用、市場別レジーム |
| `app/utils/market_utils.py` | **新規** | JP/US分類、ティッカー表示ユーティリティ |
| `app/enrichers/ticker_aliases.py` | 修正 | JP企業名エイリアス追加 |
| `app/enrichers/regime_detector.py` | 修正 | 市場別レジーム計算（US/JP） |
| `app/enrichers/monthly_analysis.py` | 修正 | `_compute_cross_market_analysis` 新設（セクション17-19） |
| `app/enrichers/propagation.py` | 修正 | JP セクター対応 |
| `app/enrichers/shock_classifier.py` | 修正 | JP記事キーワード対応 |
| `app/enrichers/hypothesis.py` | 修正 | `hypothesis_title` / `hypothesis_body` 分離 |
| `app/enrichers/market_response.py` | 修正 | `thinking_budget=0` 追加 |
| `app/enrichers/narrative_classifier.py` | 修正 | `thinking_budget=0` 追加 |
| `app/llm/gemini.py` | 修正 | `thinking_budget` パラメータ、`_parse_title_body`、`enhance_hypothesis_ja` 構造化 |
| `app/detectors/mention_anomaly.py` | 修正 | JP銘柄の言及検出対応 |
| `app/reporter/daily_report.py` | 修正 | `[US]`/`[JP]` ラベル、日本語社名表示 |
| `app/reporter/templates/*.md.j2` | 修正 | 全4テンプレートで市場ラベル・JP社名対応、セクション17-19新設 |
| `scripts/backfill_daily.py` | 修正 | `active_tickers` / `active_sector_map` 使用 |
| `configs/config.yaml` | 修正 | `market_scope`, `jp_tickers`, `jp_rss_feeds`, `jp_sector_map` |

### 変更しないファイル

| ファイル | 理由 |
|---------|------|
| セクション1-16 のロジック | 完全非破壊。セクション17-19は追加のみ |
| `database.py` スキーマ | 新規テーブル不要 |
| 既存テスト（432件） | 全パス維持 |

---

## テスト追加状況

| テストファイル | テスト数 | 対象 |
|-------------|---------|------|
| `test_market_scope.py` | **新規** | `active_tickers`, `active_sector_map`, `is_global` |
| `test_cross_market.py` | **新規** | セクション17-19: 日米ナラティブ比較、反応速度比較、移植候補 |
| `test_jp_nlp.py` | **新規** | JP銘柄エイリアス、日本語テキストマッチング |
| `test_market_utils.py` | **新規** | `is_jp_ticker`, `format_ticker_display` 等 |
| `test_regime_detector.py` | 修正 | 市場別レジーム計算テスト追加 |
| `test_monthly_analysis.py` | 修正 | `cross_market` キー追加 |

全テスト: **510件**（既存432 + 新規78）すべてパス。

---

## 検証結果

### 3ヶ月バックフィル（2025-11-24 ～ 2026-02-22）

| 指標 | 値 |
|------|-----|
| 価格データ | 1,526行（25銘柄） |
| バックフィル日数 | 32日（新規） |
| enriched_events 合計 | 266件（63日間） |
| JP銘柄イベント | 46件（全10銘柄出現） |
| narrative_snapshots | 110件 |
| regime_snapshots | 68件 |

### レポート確認

| セクション | 確認項目 | 結果 |
|-----------|---------|------|
| 日次: 構造インパクトランキング | JP銘柄が登場 | ✓ 7203.T（トヨタ）4位 |
| 日次: 波及候補 | JP→JP波及 | ✓ 7203.T→6501.T, 9984.T→6098.T |
| 日次: 市場別レジーム | US/JP個別表示 | ✓ US引き締め / JP高ボラ |
| 日次: 仮説タイトル | 切れずに完全表示 | ✓ タイトル+本文分離 |
| 週次: イベント持続性 | [JP]ラベル | ✓ 4銘柄にJPラベル |
| 月次: 構造的持続性 | JP銘柄含む | ✓ 一時的銘柄にJP6銘柄 |
| 月次: セクション17 | 日米ナラティブ比較 | ✓ AI差分+55pt |
| 月次: セクション18 | 日米反応速度比較 | ✓ US即時38% vs JP21% |
| 月次: セクション19 | ナラティブ移植候補 | ✓ 2件検出 |

### 既知の制約

| 制約 | 説明 |
|------|------|
| JP言及異常の精度 | 日本語テキストの形態素解析は未実装。キーワードマッチングベースのため、複合語の一部一致が起こりうる |
| 過去バックフィルの言及異常 | 過去のRSS/Reddit記事は取得不可。バックフィルデータは価格・出来高異常のみ |
| 過去の evidence_score | 直近数日分の記事で全期間のエビデンスを参照するため、過去日の evidence_score は低めになる |
| JP RSS フィード可用性 | 一部フィード（Reuters JP 等）は不安定。bozo error 発生時はスキップ |

---

## 品質条件の検証結果

### US モード非破壊

- `market_scope: US` 時は v8 と完全に同一の動作
- `active_tickers` = `tickers`（15銘柄）、`active_sector_map` = `sector_map`（8セクター）
- セクション17-19 は `{% if cross_market %}` ガードで GLOBAL 時のみ表示

### LLM非依存

- `thinkingBudget=0` は Gemini API のオプションパラメータ。非思考モデルでは無視される
- LLM 未設定時は全機能がテンプレートベースで動作（degraded mode 維持）

### DB書込み冪等性

- `INSERT OR IGNORE` / `ON CONFLICT UPSERT` により、バックフィルの重複実行は安全
