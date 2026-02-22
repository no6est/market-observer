"""Generate sample reports with synthetic data to demonstrate all sections.

Produces:
- reports/sample_structural_v3.md  (構造変化観測レポート with SPP column)
- reports/sample_weekly_v3.md      (週次メタ分析レポート with propagation, SPP, verification, charts)
- reports/charts/narrative_trend.png
- reports/charts/media_diffusion.png
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.enrichers.narrative_chart import generate_charts
from app.reporter.daily_report import generate_structural_report, generate_weekly_report


def _build_sample_events() -> list[dict]:
    return [
        {
            "ticker": "NVDA", "signal_type": "price_change", "z_score": 3.2,
            "shock_type": "Tech shock", "sis": 0.782,
            "sector": "AI_Infrastructure",
            "evidence_titles": ["NVIDIA announces next-gen Blackwell Ultra GPU",
                                "NVDA surges on record data center revenue forecast"],
            "narrative_category": "AI/LLM/自動化", "ai_centricity": 0.85,
            "summary": "前日比+8.2%の価格変動（Blackwell Ultra発表に伴う急騰）",
            "evidence_score": 0.82, "market_evidence": 0.90,
            "media_evidence": 0.80, "official_evidence": 0.70,
            "spp": 0.78, "diffusion_pattern": "sns_to_tier1",
            "tier1_count": 2, "tier2_count": 3, "sns_count": 12,
        },
        {
            "ticker": "PLTR", "signal_type": "mention_surge", "z_score": 5.1,
            "shock_type": "Narrative shift", "sis": 0.650,
            "sector": "Enterprise_AI",
            "evidence_titles": ["DHS Opens a Billion-Dollar Tab With Palantir",
                                "Palantir wins NATO intelligence contract"],
            "narrative_category": "AI/LLM/自動化", "ai_centricity": 0.72,
            "summary": "15件の言及（通常の25.0倍）",
            "evidence_score": 0.18, "market_evidence": 0.10,
            "media_evidence": 0.20, "official_evidence": 0.35,
            "spp": 0.45, "diffusion_pattern": "sns_only",
            "tier1_count": 0, "tier2_count": 0, "sns_count": 15,
        },
        {
            "ticker": "CRWD", "signal_type": "volume_spike", "z_score": 4.1,
            "shock_type": "Tech shock", "sis": 0.520,
            "sector": "Cloud_Security",
            "evidence_titles": ["CrowdStrike integrates AI-native threat detection"],
            "narrative_category": "AI/LLM/自動化", "ai_centricity": 0.55,
            "summary": "出来高が平均の3.1倍",
            "evidence_score": 0.15, "market_evidence": 0.30,
            "media_evidence": 0.10, "official_evidence": 0.00,
            "spp": 0.32, "diffusion_pattern": "sns_to_tier2",
            "tier1_count": 0, "tier2_count": 1, "sns_count": 5,
        },
        {
            "ticker": "XOM", "signal_type": "price_change", "z_score": 2.9,
            "shock_type": "Regulation shock", "sis": 0.480,
            "sector": "Energy",
            "evidence_titles": ["EU finalizes carbon border adjustment mechanism phase-2",
                                "Exxon accelerates CCS investment amid policy shifts"],
            "narrative_category": "エネルギー/資源", "ai_centricity": 0.08,
            "summary": "前日比-3.5%の価格変動（EU炭素規制強化への懸念）",
            "evidence_score": 0.22, "market_evidence": 0.70,
            "media_evidence": 0.00, "official_evidence": 0.00,
            "spp": 0.61, "diffusion_pattern": "tier1_direct",
            "tier1_count": 2, "tier2_count": 0, "sns_count": 3,
        },
        {
            "ticker": "JPM", "signal_type": "mention_surge", "z_score": 2.5,
            "shock_type": "Execution signal", "sis": 0.410,
            "sector": "Finance",
            "evidence_titles": ["JPMorgan warns of credit cycle turning point",
                                "Fed signals slower rate cut pace"],
            "narrative_category": "金融/金利/流動性", "ai_centricity": 0.12,
            "summary": "8件の言及（信用サイクル転換の議論拡大）",
            "evidence_score": 0.15, "market_evidence": 0.10,
            "media_evidence": 0.00, "official_evidence": 0.35,
            "spp": 0.53, "diffusion_pattern": "sns_to_tier1",
            "tier1_count": 1, "tier2_count": 0, "sns_count": 8,
        },
        {
            "ticker": "TSMC", "signal_type": "price_change", "z_score": 2.3,
            "shock_type": "Tech shock", "sis": 0.385,
            "sector": "Semiconductor",
            "evidence_titles": ["TSMC Arizona fab achieves 3nm yields matching Taiwan"],
            "narrative_category": "半導体/供給網", "ai_centricity": 0.35,
            "summary": "前日比+2.8%の価格変動（Arizona工場歩留まり改善）",
            "evidence_score": 0.45, "market_evidence": 0.70,
            "media_evidence": 0.20, "official_evidence": 0.35,
            "spp": 0.68, "diffusion_pattern": "sns_to_tier1",
            "tier1_count": 1, "tier2_count": 1, "sns_count": 4,
        },
        {
            "ticker": "META", "signal_type": "mention_surge", "z_score": 2.1,
            "shock_type": "Regulation shock", "sis": 0.350,
            "sector": "AI_Infrastructure",
            "evidence_titles": ["EU Digital Markets Act enforcement action against Meta",
                                "Meta fined €1.2B for data transfer violations"],
            "narrative_category": "規制/政策/地政学", "ai_centricity": 0.25,
            "summary": "6件の言及（EU DMA執行措置への反応）",
            "evidence_score": 0.28, "market_evidence": 0.10,
            "media_evidence": 0.40, "official_evidence": 0.35,
            "spp": 0.41, "diffusion_pattern": "sns_to_tier2",
            "tier1_count": 0, "tier2_count": 2, "sns_count": 6,
        },
    ]


def _build_sample_narrative_index() -> dict:
    return {
        "basis": "全イベント",
        "total_events": 7,
        "basis_events": 7,
        "category_distribution": {
            "AI/LLM/自動化": {"count": 3, "pct": 0.429},
            "規制/政策/地政学": {"count": 1, "pct": 0.143},
            "エネルギー/資源": {"count": 1, "pct": 0.143},
            "金融/金利/流動性": {"count": 1, "pct": 0.143},
            "半導体/供給網": {"count": 1, "pct": 0.143},
        },
        "ai_ratio": 0.472,
        "top1_concentration": 0.429,
        "historical_avg": {
            "AI/LLM/自動化": 0.250,
            "規制/政策/地政学": 0.180,
            "エネルギー/資源": 0.120,
            "金融/金利/流動性": 0.150,
            "半導体/供給網": 0.100,
            "その他": 0.100,
        },
        "warning_flags": [
            "AI比率が7日平均(25%)から18ポイント上昇しています",
        ],
    }


def _build_sample_non_ai_highlights() -> list[dict]:
    return [
        {
            "ticker": "XOM",
            "summary": "前日比-3.5%の価格変動（EU炭素規制強化への懸念）",
            "sis": 0.480, "narrative_category": "エネルギー/資源",
            "ai_centricity": 0.08, "shock_type": "Regulation shock",
            "evidence_titles": ["EU finalizes carbon border adjustment mechanism phase-2",
                                "Exxon accelerates CCS investment amid policy shifts"],
            "evidence_score": 0.22, "undercovered_score": 0.918,
        },
        {
            "ticker": "JPM",
            "summary": "8件の言及（信用サイクル転換の議論拡大）",
            "sis": 0.410, "narrative_category": "金融/金利/流動性",
            "ai_centricity": 0.12, "shock_type": "Execution signal",
            "evidence_titles": ["JPMorgan warns of credit cycle turning point",
                                "Fed signals slower rate cut pace"],
            "evidence_score": 0.15, "undercovered_score": 0.583,
        },
        {
            "ticker": "META",
            "summary": "6件の言及（EU DMA執行措置への反応）",
            "sis": 0.350, "narrative_category": "規制/政策/地政学",
            "ai_centricity": 0.25, "shock_type": "Regulation shock",
            "evidence_titles": ["EU Digital Markets Act enforcement action against Meta",
                                "Meta fined €1.2B for data transfer violations"],
            "evidence_score": 0.28, "undercovered_score": 0.496,
        },
    ]


def _build_sample_overheat_alert() -> dict:
    return {
        "severity": "warning",
        "message": (
            "ナラティブ過熱警告: AI関連が47%（7日平均25%から+22pt）、"
            "裏付けスコア中央値0.18（閾値0.3未満）、4日連続でAI優勢"
        ),
        "conditions": {
            "ai_ratio": 0.472,
            "historical_ai_avg": 0.25,
            "median_evidence_score": 0.18,
            "consecutive_ai_dominant_days": 4,
        },
        "recommendation": (
            "非AI構造変化への注目度を意図的に高めることを推奨します。"
            "AI関連ナラティブが市場の実態以上に増幅されている可能性があります。"
        ),
    }


def _build_sample_weekly_analysis() -> dict:
    narrative_trend = [
        {"date": "2026-01-16", "categories": {
            "AI/LLM/自動化": 0.30, "規制/政策/地政学": 0.20,
            "金融/金利/流動性": 0.15, "エネルギー/資源": 0.15,
            "半導体/供給網": 0.10, "ガバナンス/経営": 0.05, "その他": 0.05}},
        {"date": "2026-01-17", "categories": {
            "AI/LLM/自動化": 0.35, "規制/政策/地政学": 0.18,
            "金融/金利/流動性": 0.15, "エネルギー/資源": 0.12,
            "半導体/供給網": 0.10, "ガバナンス/経営": 0.05, "その他": 0.05}},
        {"date": "2026-01-18", "categories": {
            "AI/LLM/自動化": 0.38, "規制/政策/地政学": 0.17,
            "金融/金利/流動性": 0.14, "エネルギー/資源": 0.11,
            "半導体/供給網": 0.10, "ガバナンス/経営": 0.05, "その他": 0.05}},
        {"date": "2026-01-19", "categories": {
            "AI/LLM/自動化": 0.42, "規制/政策/地政学": 0.15,
            "金融/金利/流動性": 0.13, "エネルギー/資源": 0.12,
            "半導体/供給網": 0.08, "ガバナンス/経営": 0.05, "その他": 0.05}},
        {"date": "2026-01-20", "categories": {
            "AI/LLM/自動化": 0.45, "規制/政策/地政学": 0.14,
            "金融/金利/流動性": 0.13, "エネルギー/資源": 0.10,
            "半導体/供給網": 0.08, "ガバナンス/経営": 0.05, "その他": 0.05}},
        {"date": "2026-01-21", "categories": {
            "AI/LLM/自動化": 0.48, "規制/政策/地政学": 0.13,
            "金融/金利/流動性": 0.12, "エネルギー/資源": 0.10,
            "半導体/供給網": 0.08, "ガバナンス/経営": 0.04, "その他": 0.05}},
        {"date": "2026-01-22", "categories": {
            "AI/LLM/自動化": 0.47, "規制/政策/地政学": 0.14,
            "金融/金利/流動性": 0.14, "エネルギー/資源": 0.10,
            "半導体/供給網": 0.08, "ガバナンス/経営": 0.03, "その他": 0.04}},
    ]

    propagation_structure = {
        "sns_only": 8,
        "sns_to_tier2": 6,
        "sns_to_tier1": 10,
        "tier1_direct": 4,
        "no_coverage": 3,
    }

    spp_top3 = [
        {"ticker": "NVDA", "spp": 0.78, "summary": "Blackwell Ultra発表に伴う構造的GPU需要シフト",
         "shock_type": "Tech shock", "diffusion_pattern": "sns_to_tier1"},
        {"ticker": "TSMC", "spp": 0.68, "summary": "Arizona工場3nm歩留まり改善による供給網再編",
         "shock_type": "Tech shock", "diffusion_pattern": "sns_to_tier1"},
        {"ticker": "XOM", "spp": 0.61, "summary": "EU炭素規制Phase-2によるコスト構造変化",
         "shock_type": "Regulation shock", "diffusion_pattern": "tier1_direct"},
    ]

    # Verification: 2 weeks of prediction data, 5 verdicts
    verification_summary = {
        "total_predictions": 5,
        "tp": 2,  # overheat warned correctly (AI hype subsided, prices dropped)
        "fp": 1,  # overheat warned but events were real structural changes
        "tn": 1,  # no warning, and market was indeed stable
        "fn": 1,  # missed: should have warned about energy sector overheating
        "precision": 0.667,  # 2/(2+1)
        "recall": 0.667,     # 2/(2+1)
        "verdicts": [
            {"prediction_date": "2026-01-10", "verdict": "TP",
             "details": "AI過熱警告を発出→翌週AI関連3銘柄が5%以上下落、裏付けなしのナラティブが収束"},
            {"prediction_date": "2026-01-12", "verdict": "FP",
             "details": "AI過熱警告を発出→しかしNVDA Blackwell発表は構造的変化であり、価格は維持"},
            {"prediction_date": "2026-01-14", "verdict": "TP",
             "details": "AI過熱警告を発出→SNS起点のPLTR言及が急減、Tier1メディア未追随"},
            {"prediction_date": "2026-01-17", "verdict": "TN",
             "details": "警告なし→市場は安定推移、ナラティブ分布も均衡を維持"},
            {"prediction_date": "2026-01-19", "verdict": "FN",
             "details": "警告なし→エネルギーセクターで規制ショックが過熱していたが検出できず"},
        ],
    }

    chart_paths = {
        "trend_chart": "charts/narrative_trend.png",
        "diffusion_chart": "charts/media_diffusion.png",
    }

    return {
        "period": "過去7日間",
        "shock_type_distribution": {
            "テクノロジーショック": 12, "ナラティブシフト": 8,
            "規制ショック": 5, "業績シグナル": 4, "ビジネスモデルショック": 2,
        },
        "narrative_trend": narrative_trend,
        "non_ai_highlights": [
            {"ticker": "XOM", "summary": "EU炭素規制強化による構造的コスト変化", "score": 0.480},
            {"ticker": "JPM", "summary": "信用サイクル転換シグナル", "score": 0.410},
            {"ticker": "META", "summary": "EU DMA執行措置", "score": 0.350},
        ],
        "turning_point_candidates": [
            {"category": "AI/LLM/自動化", "direction": "上昇", "delta": 0.170,
             "description": "「AI/LLM/自動化」が17ポイント上昇（30% → 47%）"},
        ],
        "org_impact_hypotheses": [
            {"hypothesis": "今週の構造変化は「テクノロジーショック」に集中（39%）。この領域の専門知識・人材の重要性が高まっている可能性。",
             "evidence": "ショックタイプ分布: テクノロジーショックが12件"},
            {"hypothesis": "「AI/LLM/自動化」ナラティブの急上昇は、この分野への注目シフトを示唆。関連するリスク管理体制の見直しが必要かもしれません。",
             "evidence": "「AI/LLM/自動化」が17ポイント上昇（30% → 47%）"},
        ],
        "bias_correction_actions": [
            {"action": "「社会/労働/教育」の監視比重を引き上げ",
             "reason": "ナラティブ比率0%と低いが、過去7日で1件のイベントが検出されており、見落としリスクがあります。",
             "category": "社会/労働/教育", "current_pct": 0.0},
            {"action": "「ガバナンス/経営」の監視比重を引き上げ",
             "reason": "ナラティブ比率3%と低いが、過去7日で2件のイベントが検出されており、見落としリスクがあります。",
             "category": "ガバナンス/経営", "current_pct": 0.03},
            {"action": "「AI/LLM/自動化」の過集中に注意",
             "reason": "ナラティブ比率47%と高く、他カテゴリの構造変化を見落とすリスクがあります。",
             "category": "AI/LLM/自動化", "current_pct": 0.47},
        ],
        "propagation_structure": propagation_structure,
        "spp_top3": spp_top3,
        "verification_summary": verification_summary,
        "chart_paths": chart_paths,
    }


def main() -> None:
    output_dir = Path("reports")
    output_dir.mkdir(parents=True, exist_ok=True)
    chart_dir = output_dir / "charts"
    chart_dir.mkdir(parents=True, exist_ok=True)
    date = "2026-01-22"

    events = _build_sample_events()
    weekly_analysis = _build_sample_weekly_analysis()

    # Generate charts from weekly analysis data
    chart_paths = generate_charts(
        narrative_trend=weekly_analysis["narrative_trend"],
        propagation_data=weekly_analysis["propagation_structure"],
        output_dir=str(chart_dir),
    )
    print(f"Charts generated: {chart_paths}")

    structural_themes = [
        {"name": "AI基盤セクターのテクノロジーショック連鎖", "shock_type": "Tech shock",
         "tickers": ["NVDA", "CRWD"], "sector": "AI_Infrastructure", "sis_avg": 0.651,
         "keywords": ["blackwell", "AI", "GPU", "threat detection"],
         "description": "NVIDIA Blackwell Ultra発表とCrowdStrikeのAIネイティブ脅威検出統合が同時発生。AI基盤の計算能力とセキュリティの両面で構造転換が進行中。"},
        {"name": "エネルギー政策の規制強化シグナル", "shock_type": "Regulation shock",
         "tickers": ["XOM", "META"], "sector": "Energy", "sis_avg": 0.415,
         "keywords": ["carbon", "EU", "regulation", "DMA"],
         "description": "EU炭素規制Phase-2とDMA執行が同時に進行。エネルギーとテクノロジーの両セクターで規制リスクが顕在化。"},
        {"name": "金融セクターの信用サイクル転換議論", "shock_type": "Execution signal",
         "tickers": ["JPM"], "sector": "Finance", "sis_avg": 0.410,
         "keywords": ["credit cycle", "rate cuts", "Fed"],
         "description": "JPMorganの信用サイクル転換警告とFedの利下げペース鈍化シグナルが重なり、金融市場全体のリスク認識が変化中。"},
    ]
    causal_chains = [
        {"ticker": "NVDA", "shock_type": "Tech shock",
         "text_graph": "```\nNVDA: 前日比+8.2%の価格変動\n  └→ Blackwell Ultra GPU発表（データセンター収益予測過去最高）\n    └→ AI計算能力の世代交代、AMD/SMCI/AVGOへの波及可能性\n```"},
        {"ticker": "XOM", "shock_type": "Regulation shock",
         "text_graph": "```\nXOM: 前日比-3.5%の価格変動\n  └→ EU炭素国境調整メカニズムPhase-2確定\n    └→ エネルギーセクター全体のコスト構造変化、CVX/SLB/HALへ波及\n```"},
    ]
    hypotheses = [
        {"hypothesis": "NVDAの急騰はBlackwell Ultra発表による構造的需要シフトの始まり",
         "confidence": 0.82, "context": "GPU世代交代は過去にも大幅な株価再評価を引き起こしてきた",
         "evidence_titles": ["NVIDIA announces next-gen Blackwell Ultra GPU"],
         "evidence": ["https://example.com/nvda-blackwell"],
         "counterpoints": ["供給制約が需要を満たせない場合、期待が先行している可能性"]},
        {"hypothesis": "EU規制強化がエネルギー・テック両セクターの構造コスト上昇を加速",
         "confidence": 0.70, "context": "CBAMとDMAの同時進行は異例",
         "evidence_titles": ["EU finalizes carbon border adjustment mechanism phase-2"],
         "evidence": ["https://example.com/eu-cbam"],
         "counterpoints": ["規制執行のタイムラインが延長される可能性がある"]},
    ]
    propagation = [
        {"source_ticker": "NVDA", "related_tickers": ["AMD", "SMCI", "AVGO"],
         "sector": "AI_Infrastructure", "reason": "NVDAの価格変動異常により、AI基盤セクターに波及可能性"},
        {"source_ticker": "XOM", "related_tickers": ["CVX", "SLB", "HAL"],
         "sector": "Energy", "reason": "XOMの規制ショックにより、エネルギーセクターに波及可能性"},
    ]
    structural_questions = [
        "このテクノロジーショックが構造的変化である場合、6ヶ月後にAI基盤セクターのサプライチェーンはどう再編されるか？",
        "AI/LLM/自動化ナラティブの急上昇が一時的なバブルではなく構造的シフトである証拠は何か？",
        "信用サイクル転換と規制強化が同時進行する場合、セクター間のリスク波及経路はどう変わるか？",
    ]
    tracking_queries = [
        '"NVDA" AND (disruption OR technology OR AI) since:2026-01-22',
        '"XOM" AND (regulation OR policy OR compliance) since:2026-01-22',
        '"JPM" AND (earnings OR news) since:2026-01-22',
    ]

    structural_md = generate_structural_report(
        events=events,
        structural_themes=structural_themes,
        causal_chains=causal_chains,
        hypotheses=hypotheses,
        propagation=propagation,
        structural_questions=structural_questions,
        tracking_queries=tracking_queries,
        date=date,
        narrative_index=_build_sample_narrative_index(),
        non_ai_highlights=_build_sample_non_ai_highlights(),
        overheat_alert=_build_sample_overheat_alert(),
    )
    structural_path = output_dir / f"sample_structural_{date}.md"
    structural_path.write_text(structural_md, encoding="utf-8")
    print(f"Structural report: {structural_path}")

    weekly_md = generate_weekly_report(
        analysis=weekly_analysis, date=date
    )
    weekly_path = output_dir / f"sample_weekly_{date}.md"
    weekly_path.write_text(weekly_md, encoding="utf-8")
    print(f"Weekly report: {weekly_path}")


if __name__ == "__main__":
    main()
