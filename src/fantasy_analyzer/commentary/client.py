"""Anthropic-backed commentary generation client (FFA-094).

Turns a prompt string built by ``commentary/prompts.py`` into finished
commentary text by calling the Claude API. This is the only module in
``commentary`` that makes a network call -- ``context.py`` and ``prompts.py``
stay pure per AGENTS.md's "keep API/network code isolated from calculations"
rule.

Credentials come from the environment (``ANTHROPIC_API_KEY``) via the
``anthropic`` SDK's default resolution -- this module never hardcodes a key.
The default model is ``claude-opus-4-8`` at ``effort="high"``
(:data:`DEFAULT_MODEL` / :data:`DEFAULT_EFFORT`), per the FFA-094 API-billing
decision. Both are ordinary keyword arguments on :meth:`CommentaryClient.generate`,
never hardcoded past the defaults.

Tests inject a fake object satisfying the ``messages.create(...)`` surface
via :class:`CommentaryClient`'s ``client`` parameter, so the unit test suite
never makes a live API call, per AGENTS.md's "unit tests must not depend on
Sleeper [or any external API] being online" rule.
"""

from __future__ import annotations

from typing import Any, Optional, Protocol

import anthropic

#: Default model for commentary generation, per the FFA-094 billing decision.
DEFAULT_MODEL = "claude-opus-4-8"

#: Default reasoning/response effort for commentary generation.
DEFAULT_EFFORT = "high"

#: Default output token ceiling -- generous for a multi-matchup recap while
#: staying well under the non-streaming SDK timeout.
DEFAULT_MAX_TOKENS = 4096


class CommentaryGenerationError(RuntimeError):
    """Raised when the Anthropic API fails to produce commentary text."""


class _MessagesClient(Protocol):
    """Structural type for the ``client.messages`` surface this module uses."""

    def create(self, **kwargs: Any) -> Any: ...


class _AnthropicLike(Protocol):
    messages: _MessagesClient


class CommentaryClient:
    """Thin wrapper around the Anthropic Messages API for commentary text.

    Args:
        api_key: Explicit API key. Defaults to ``None``, in which case the
            underlying ``anthropic.Anthropic()`` client resolves credentials
            from the environment (``ANTHROPIC_API_KEY``, ``ANTHROPIC_AUTH_TOKEN``,
            or an ``ant auth login`` profile).
        client: An already-constructed client exposing a ``messages.create``
            method. Defaults to ``None``, in which case a real
            ``anthropic.Anthropic`` client is built. Tests should inject a
            fake here instead of relying on ``api_key``.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        client: Optional[_AnthropicLike] = None,
    ) -> None:
        self._client: _AnthropicLike = client or anthropic.Anthropic(api_key=api_key)

    def generate(
        self,
        prompt: str,
        *,
        model: str = DEFAULT_MODEL,
        effort: str = DEFAULT_EFFORT,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> str:
        """Send ``prompt`` to Claude and return the generated commentary text.

        Args:
            prompt: A ready-to-send prompt, typically produced by
                ``commentary/prompts.py``.
            model: Anthropic model ID. Defaults to :data:`DEFAULT_MODEL`.
            effort: ``output_config.effort`` value (``"low"`` through
                ``"max"``). Defaults to :data:`DEFAULT_EFFORT`.
            max_tokens: Output token ceiling. Defaults to
                :data:`DEFAULT_MAX_TOKENS`.

        Returns:
            The concatenated text of every ``text`` content block in the
            response.

        Raises:
            CommentaryGenerationError: If the API call fails, or if the
                response contains no text content.
        """
        try:
            response = self._client.messages.create(
                model=model,
                max_tokens=max_tokens,
                output_config={"effort": effort},
                messages=[{"role": "user", "content": prompt}],
            )
        except anthropic.APIError as exc:
            raise CommentaryGenerationError(
                f"Anthropic API request failed: {exc}"
            ) from exc

        text = "".join(
            block.text
            for block in response.content
            if getattr(block, "type", None) == "text"
        )
        if not text:
            raise CommentaryGenerationError(
                "Anthropic response contained no text content "
                f"(stop_reason={getattr(response, 'stop_reason', None)!r})."
            )
        return text
