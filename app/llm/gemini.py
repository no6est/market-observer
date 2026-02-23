"""Gemini API client for report quality enhancement."""

from __future__ import annotations

import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)

_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


class GeminiClient:
    """Lightweight Gemini REST API client using requests."""

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash") -> None:
        self.api_key = api_key
        self.model = model
        self._url = f"{_API_BASE}/{model}:generateContent"

    def generate(
        self,
        prompt: str,
        max_tokens: int = 1024,
        thinking_budget: int | None = None,
    ) -> str | None:
        """Send a prompt to Gemini and return the text response.

        Args:
            prompt: The text prompt.
            max_tokens: Maximum output tokens (includes thinking tokens
                for thinking-capable models like gemini-3-*).
            thinking_budget: If set, controls thinking token budget.
                Use 0 to disable thinking for deterministic/structured tasks.

        Returns None on failure (non-critical path).
        """
        gen_config: dict = {
            "maxOutputTokens": max_tokens,
            "temperature": 0.3,
        }
        if thinking_budget is not None:
            gen_config["thinkingConfig"] = {"thinkingBudget": thinking_budget}
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": gen_config,
        }
        try:
            resp = requests.post(
                self._url,
                params={"key": self.api_key},
                json=payload,
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            candidates = data.get("candidates", [])
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                if parts:
                    return parts[0].get("text", "")
            logger.warning("Gemini returned no candidates")
            return None
        except Exception:
            logger.exception("Gemini API call failed")
            return None

    def summarize_anomaly_ja(self, anomaly: dict[str, Any]) -> str | None:
        """Generate a concise Japanese summary for an anomaly."""
        prompt = (
            "あなたは金融市場アナリストです。以下の異常検出データについて、"
            "1文の簡潔な日本語サマリーを生成してください。投資助言は含めないこと。\n\n"
            f"銘柄: {anomaly.get('ticker')}\n"
            f"シグナル種別: {anomaly.get('signal_type')}\n"
            f"スコア: {anomaly.get('score')}\n"
            f"z-score: {anomaly.get('z_score')}\n"
            f"詳細: {anomaly.get('details', {})}\n\n"
            "サマリー（1文、日本語）:"
        )
        return self.generate(prompt, max_tokens=200, thinking_budget=0)

    def enhance_hypothesis_ja(
        self, hypothesis_text: str, evidence_titles: list[str]
    ) -> dict[str, str] | None:
        """Rewrite a hypothesis in natural Japanese with evidence context.

        Returns a dict with 'title' (short heading) and 'body' (explanation),
        or None on failure.
        """
        evidence_str = "\n".join(f"- {t}" for t in evidence_titles[:5]) or "なし"
        prompt = (
            "以下の市場仮説を、自然な日本語で書き直してください。\n"
            "客観的な分析トーンで、投資助言は含めないこと。\n\n"
            "以下のフォーマットで出力してください:\n"
            "タイトル: （25文字以内の短い見出し。末尾に句点不要）\n"
            "本文: （2-3文の説明）\n\n"
            f"元の仮説: {hypothesis_text}\n"
            f"関連ニュース:\n{evidence_str}\n\n"
            "出力:"
        )
        raw = self.generate(prompt, max_tokens=300, thinking_budget=0)
        if not raw:
            return None
        return self._parse_title_body(raw)

    @staticmethod
    def _parse_title_body(text: str) -> dict[str, str]:
        """Parse 'タイトル: ...\n本文: ...' format into a dict."""
        title = ""
        body = ""
        section = None  # "title" or "body"
        for line in text.strip().splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("タイトル:") or stripped.startswith("タイトル："):
                title = stripped.split(":", 1)[-1].split("：", 1)[-1].strip()
                section = "title"
            elif stripped.startswith("本文:") or stripped.startswith("本文："):
                body = stripped.split(":", 1)[-1].split("：", 1)[-1].strip()
                section = "body"
            elif section == "body":
                # Continuation of body (multi-line)
                body += stripped
            elif section == "title" and not body:
                # Unlabeled text after title → treat as body
                body = stripped
                section = "body"
        return {"title": title, "body": body}

    def generate_theme_name_ja(self, keywords: list[str]) -> str | None:
        """Generate a descriptive Japanese theme name from keywords."""
        kw_str = ", ".join(keywords[:8])
        prompt = (
            "以下のキーワード群に対して、市場テーマとして適切な"
            "日本語の短いタイトル（10文字以内）を1つだけ出力してください。\n\n"
            f"キーワード: {kw_str}\n\n"
            "テーマ名:"
        )
        result = self.generate(prompt, max_tokens=50, thinking_budget=0)
        if result:
            return result.strip().strip('"').strip("「」")
        return None


def create_gemini_client(
    api_key: str | None, model: str = "gemini-2.0-flash"
) -> GeminiClient | None:
    """Create a Gemini client if API key is available. Returns None otherwise."""
    if not api_key:
        logger.info("Gemini API key not configured; LLM enhancement disabled")
        return None
    logger.info("Gemini client initialized (model=%s)", model)
    return GeminiClient(api_key=api_key, model=model)
