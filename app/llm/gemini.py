"""Gemini API client for report quality enhancement."""

from __future__ import annotations

import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)

_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

# Thinking models count reasoning tokens against maxOutputTokens, so a small
# budget gets consumed by thinking and the visible answer is cut mid-sentence.
# Reserve extra room on top of the caller's visible-output budget.
_THINKING_TOKEN_RESERVE = 2048


def _thinking_config(model: str) -> dict[str, Any] | None:
    """Return a thinkingConfig that keeps reasoning minimal, or None if unsupported."""
    if model.startswith("gemini-3"):
        return {"thinkingLevel": "low"}
    if model.startswith("gemini-2.5-flash"):
        return {"thinkingBudget": 0}
    return None


class GeminiClient:
    """Lightweight Gemini REST API client using requests."""

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash") -> None:
        self.api_key = api_key
        self.model = model
        self._url = f"{_API_BASE}/{model}:generateContent"

    def _build_payload(self, prompt: str, max_tokens: int) -> dict[str, Any]:
        """Build the generateContent request body.

        ``max_tokens`` is the budget for the visible answer; thinking models
        get an additional reserve so reasoning does not truncate the answer.
        """
        generation_config: dict[str, Any] = {
            "maxOutputTokens": max_tokens,
            "temperature": 0.3,
        }
        thinking = _thinking_config(self.model)
        if thinking is not None:
            generation_config["thinkingConfig"] = thinking
            generation_config["maxOutputTokens"] = max_tokens + _THINKING_TOKEN_RESERVE
        return {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": generation_config,
        }

    @staticmethod
    def _extract_text(data: dict[str, Any]) -> str | None:
        """Extract the answer text from a response, rejecting truncated output.

        Returns None when there is no candidate or the answer was cut off by
        the token limit, so callers fall back to their deterministic templates
        instead of publishing a half sentence.
        """
        candidates = data.get("candidates", [])
        if not candidates:
            logger.warning("Gemini returned no candidates")
            return None
        candidate = candidates[0]
        finish_reason = candidate.get("finishReason")
        if finish_reason == "MAX_TOKENS":
            logger.warning(
                "Gemini output truncated (finishReason=MAX_TOKENS, usage=%s); discarding",
                data.get("usageMetadata"),
            )
            return None
        if finish_reason not in (None, "STOP"):
            logger.warning("Gemini finished abnormally (finishReason=%s); discarding", finish_reason)
            return None
        parts = candidate.get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        return text or None

    def generate(self, prompt: str, max_tokens: int = 1024) -> str | None:
        """Send a prompt to Gemini and return the text response.

        Returns None on failure or truncated output (non-critical path).
        """
        payload = self._build_payload(prompt, max_tokens)
        try:
            resp = requests.post(
                self._url,
                params={"key": self.api_key},
                json=payload,
                timeout=30,
            )
            resp.raise_for_status()
            return self._extract_text(resp.json())
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
        return self.generate(prompt, max_tokens=200)

    def enhance_hypothesis_ja(
        self, hypothesis_text: str, evidence_titles: list[str]
    ) -> str | None:
        """Rewrite a hypothesis in natural Japanese with evidence context."""
        evidence_str = "\n".join(f"- {t}" for t in evidence_titles[:5]) or "なし"
        prompt = (
            "以下の市場仮説を、自然な日本語で書き直してください。"
            "客観的な分析トーンで、投資助言は含めないこと。2-3文程度。\n\n"
            f"元の仮説: {hypothesis_text}\n"
            f"関連ニュース:\n{evidence_str}\n\n"
            "日本語仮説:"
        )
        return self.generate(prompt, max_tokens=300)

    def generate_theme_name_ja(self, keywords: list[str]) -> str | None:
        """Generate a descriptive Japanese theme name from keywords."""
        kw_str = ", ".join(keywords[:8])
        prompt = (
            "以下のキーワード群に対して、市場テーマとして適切な"
            "日本語の短いタイトル（10文字以内）を1つだけ出力してください。\n\n"
            f"キーワード: {kw_str}\n\n"
            "テーマ名:"
        )
        result = self.generate(prompt, max_tokens=50)
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
