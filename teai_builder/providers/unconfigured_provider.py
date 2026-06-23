"""Fallback provider used when no LLM is configured yet."""

from __future__ import annotations

from typing import Any

from teai_builder.providers.base import LLMProvider, LLMResponse


class UnconfiguredProvider(LLMProvider):
    def __init__(self) -> None:
        super().__init__(api_key=None, api_base=None)

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> LLMResponse:
        return LLMResponse(
            content=(
                "No LLM provider is configured yet. Please configure a provider "
                "and API key in the WebUI settings before starting a task."
            ),
            finish_reason="stop",
        )

    def get_default_model(self) -> str:
        return "unconfigured"
