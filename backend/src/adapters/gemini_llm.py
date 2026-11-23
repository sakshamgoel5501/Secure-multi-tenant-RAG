from __future__ import annotations

from collections.abc import AsyncIterator

from google import genai
from google.genai import types


class GeminiLLM:
    """Gemini on Vertex AI. The system prompt is a fixed constant and retrieved text only ever
    goes in the user turn. No tools are configured, so nothing in a document can trigger an action.

    thinking_budget=0 turns off the model's hidden reasoning pass, which for a short extractive
    answer only adds latency. Pass None to leave the model default (needed for models that can't
    disable thinking)."""

    def __init__(
        self,
        project: str,
        location: str,
        model: str,
        *,
        max_output_tokens: int = 512,
        thinking_budget: int | None = 0,
    ) -> None:
        self._client = genai.Client(vertexai=True, project=project, location=location)
        self._model = model
        self._max_tokens = max_output_tokens
        self._thinking = (
            types.ThinkingConfig(thinking_budget=thinking_budget)
            if thinking_budget is not None
            else None
        )

    def _config(self, system: str) -> types.GenerateContentConfig:
        return types.GenerateContentConfig(
            system_instruction=system,
            temperature=0.0,
            max_output_tokens=self._max_tokens,
            thinking_config=self._thinking,
        )

    async def generate(self, system: str, user: str) -> str:
        resp = await self._client.aio.models.generate_content(
            model=self._model, contents=user, config=self._config(system)
        )
        return resp.text or ""

    async def stream(self, system: str, user: str) -> AsyncIterator[str]:
        pieces = await self._client.aio.models.generate_content_stream(
            model=self._model, contents=user, config=self._config(system)
        )
        async for chunk in pieces:
            if chunk.text:
                yield chunk.text

                