"""Tests for GeminiClient request building and response parsing (no network)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from app.llm.gemini import GeminiClient


def _response(text_parts: list[dict[str, Any]], finish_reason: str | None = "STOP") -> dict[str, Any]:
    candidate: dict[str, Any] = {"content": {"parts": text_parts}}
    if finish_reason is not None:
        candidate["finishReason"] = finish_reason
    return {"candidates": [candidate]}


class TestBuildPayload:
    def test_gemini3_adds_thinking_config_and_reserve(self) -> None:
        client = GeminiClient(api_key="k", model="gemini-3-flash-preview")
        cfg = client._build_payload("p", max_tokens=300)["generationConfig"]
        assert cfg["thinkingConfig"] == {"thinkingLevel": "low"}
        assert cfg["maxOutputTokens"] > 300

    def test_gemini25_flash_disables_thinking(self) -> None:
        client = GeminiClient(api_key="k", model="gemini-2.5-flash")
        cfg = client._build_payload("p", max_tokens=300)["generationConfig"]
        assert cfg["thinkingConfig"] == {"thinkingBudget": 0}

    def test_non_thinking_model_unchanged(self) -> None:
        client = GeminiClient(api_key="k", model="gemini-2.0-flash")
        cfg = client._build_payload("p", max_tokens=300)["generationConfig"]
        assert "thinkingConfig" not in cfg
        assert cfg["maxOutputTokens"] == 300


class TestExtractText:
    def test_returns_text_on_stop(self) -> None:
        assert GeminiClient._extract_text(_response([{"text": "完了した文。"}])) == "完了した文。"

    def test_truncated_output_is_discarded(self) -> None:
        data = _response([{"text": "本日の市場は「引き締め」レジーム下にあり、半導体および"}], "MAX_TOKENS")
        assert GeminiClient._extract_text(data) is None

    def test_abnormal_finish_is_discarded(self) -> None:
        assert GeminiClient._extract_text(_response([{"text": "x"}], "SAFETY")) is None

    def test_thought_parts_are_skipped_and_text_joined(self) -> None:
        parts = [{"text": "internal reasoning", "thought": True}, {"text": "前半"}, {"text": "後半。"}]
        assert GeminiClient._extract_text(_response(parts)) == "前半後半。"

    def test_no_candidates_returns_none(self) -> None:
        assert GeminiClient._extract_text({"candidates": []}) is None

    def test_empty_text_returns_none(self) -> None:
        assert GeminiClient._extract_text(_response([])) is None


class TestGenerate:
    def test_generate_returns_none_when_truncated(self) -> None:
        client = GeminiClient(api_key="k", model="gemini-3-flash-preview")
        resp = MagicMock()
        resp.json.return_value = _response([{"text": "途中で"}], "MAX_TOKENS")
        with patch("app.llm.gemini.requests.post", return_value=resp) as post:
            assert client.generate("p", max_tokens=200) is None
        sent = post.call_args.kwargs["json"]["generationConfig"]
        assert sent["thinkingConfig"] == {"thinkingLevel": "low"}

    def test_generate_returns_none_on_http_error(self) -> None:
        client = GeminiClient(api_key="k")
        with patch("app.llm.gemini.requests.post", side_effect=RuntimeError("boom")):
            assert client.generate("p") is None
