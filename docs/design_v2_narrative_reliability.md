# 設計メモ: ナラティブ整合性・信頼性強化 (v2)

## 変更の目的

日次/週次レポートの「社内運用に耐える整合性と信頼性」を確保する。

### 3つのゴール

1. **指標の矛盾排除**: ナラティブ分布・AI比率・過熱警告が同一母集団に基づく
2. **過熱警告の精度向上**: 裏付けのない過熱のみ警告（実態あるAI急騰は除外）
3. **非AI構造変化の可視化**: AIノイズに隠れた「静かに重要な」変化を検出

---

## 変更サマリー

| # | 変更 | 新規/変更ファイル |
|---|------|-------------------|
| 1 | `narrative_basis` で母集団を統一 | `narrative_concentration.py`, `config.py`, `config.yaml` |
| 2 | `evidence_score` (0-1) の導入 | `evidence_scorer.py` (新規), `database.py`, `__main__.py` |
| 3 | 過熱警告をエビデンスベースに改修 | `narrative_overheat.py` |
| 4 | `undercovered_score` で非AIランキング | `non_ai_highlights.py` |
| 5 | 週次バイアス補正アクション | `weekly_analysis.py` |

---

## 1. narrative_basis（母集団統一）

**課題**: ナラティブ分布とAI比率の母集団が暗黙的で、読者が混乱する可能性。

**対策**: `narrative_basis` パラメータで母集団を明示的に選択。

```
all_events   → 全イベント（デフォルト）
top_ranked   → SIS ≥ 0.3 のみ
social_only  → mention_surge のみ
```

レポート上に「母集団: 全イベント（7件）」と表示し、下流指標（AI比率、集中度、過熱判定）が同一母集団であることを保証。

## 2. evidence_score

**課題**: イベントの「裏付け度」が未定量。

**対策**: 3軸の加重平均スコア (0.0〜1.0) を導入。

| 軸 | 重み | 算出方法 |
|----|------|----------|
| market_evidence | 0.40 | signal_type (price=0.7, volume=0.5, mention=0.1) + z_score bonus |
| media_evidence | 0.35 | Tier1記事×0.4 + Tier2記事×0.2, cap 1.0 |
| official_evidence | 0.25 | SEC/決算等キーワード検出, 0.35/hit, cap 1.0 |

**Tier1**: reuters, bloomberg, wsj, nytimes, ft, apnews, bbc, cnbc, sec.gov
**Tier2**: techcrunch, arstechnica, theverge, wired, forbes, neowin, protocol, semafor, axios

DB に4カラム追加（evidence_score, market_evidence, media_evidence, official_evidence）。

## 3. 過熱警告 v2

**課題**: v1は「AI比率 > 50% AND 価格裏付けなし AND 3日連続」で、実態あるAI急騰でも誤報。

**対策**: 3条件をすべてエビデンスベースに改修。

| 条件 | v1 | v2 |
|------|-----|-----|
| AI比率 | > 50%（絶対値） | > 7日平均 + delta_threshold (0.15) |
| 裏付け | 価格シグナル有無 | median(evidence_score of AI events) < 0.3 |
| 連続性 | 3日連続AI優勢 | N日連続AI優勢（設定可能） |

**効果**: NVDA +8.2% のような実態あるAI急騰（evidence_score=0.82）は、median を引き上げるため警告を抑制。一方、PLTRのような言及のみの事象（evidence_score=0.18）が多数の場合に正しく発火。

## 4. undercovered_score

**課題**: 非AIハイライトがSIS順のみで、「注目されていない」度合いが不明。

**対策**: 3成分の複合スコアで「静かに重要」なイベントを優先。

```
undercovered_score = sis_factor(0.4) + coverage_deficit(0.3) + market_signal(0.3)

sis_factor      = min(SIS / 0.5, 1.0)          # SISが高いほど重要
coverage_deficit = max(0, 1 - evidence_score)    # 裏付けが低いほど注目不足
market_signal   = 1.0 if price/volume else 0.0   # 実際の市場動きあり
```

**例**: XOM（SIS=0.48, evidence=0.22, price_change）→ undercovered=0.918（高SIS + 低報道 + 実需）

## 5. バイアス補正アクション（週次）

**課題**: 週次レポートが「観測結果」のみで、翌週の行動指針なし。

**対策**: 8カテゴリ均等分布（12.5%）を基準に偏りを検出。

| パターン | アクション |
|----------|-----------|
| < 6.25% AND イベントあり | 「引き上げ」推奨 |
| < 6.25% AND イベントなし AND 構造重要 | 「維持・注視」推奨 |
| > 25% | 「過集中に注意」警告 |

構造重要カテゴリ: 規制/政策/地政学, 金融/金利/流動性, エネルギー/資源

---

## テスト

| 項目 | 件数 |
|------|------|
| v1時点のテスト | 159 |
| 新規追加 | 38 |
| **合計** | **197** |

新規テストファイル: `tests/test_evidence_scorer.py` (22件)
既存テスト更新: narrative_concentration (+4), narrative_overheat (全面改修), non_ai_highlights (+6), weekly_analysis (+2), app_storage (+2)

---

## 設定パラメータ

`configs/config.yaml` の `narrative:` セクション:

```yaml
narrative:
  ai_threshold: 0.3
  overheat_ai_pct: 0.5
  overheat_streak_days: 3
  ai_surge_threshold: 0.15
  narrative_basis: all_events          # 新規
  overheat_delta_threshold: 0.15       # 新規
  overheat_evidence_threshold: 0.3     # 新規
```

---

## レポート構造（最終）

### 日次レポート
1. 構造インパクトランキング（+ 裏付けスコア列）
2. ナラティブ分布（+ 母集団表示）
3. 非AI構造変化ハイライト（+ undercovered_score）
4. 構造変化テーマ
5. 因果チェーン
6. 仮説
7. 波及候補
8. ナラティブ健全性評価（エビデンスベース過熱警告）
9. 構造変化である場合の問い
10. 追跡クエリ

### 週次レポート
1. ショックタイプ分布
2. ナラティブ推移（7日間）
3. 非AIハイライト
4. 転換点候補
5. 組織インパクト仮説
6. 来週の監視比重提案（バイアス補正）
