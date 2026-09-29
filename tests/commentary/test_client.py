"""Tests for ``commentary/client.py`` (FFA-094).

``CommentaryClient`` accepts an injected fake client exposing a
``messages.create`` surface, so these tests never call the real Anthropic
API -- consistent with AGENTS.md's "unit tests must not depend on [an
external API] being online" rule.
"""

from __future__ import annotations

import anthropic
import pytest

from fantasy_analyzer.commentary.client import (
    DEFAULT_EFFORT,
    DEFAULT_MODEL,
    CommentaryClient,
    CommentaryGenerationError,
)


class _FakeTextBlock:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _FakeThinkingBlock:
    def __init__(self) -> None:
        self.type = "thinking"
        self.thinking = "internal reasoning, not returned by generate()"


class _FakeResponse:
    def __init__(self, content: list, *, stop_reason: str = "end_turn") -> None:
        self.content = content
        self.stop_reason = stop_reason


class _FakeMessages:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response
        self.last_kwargs: dict | None = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return self._response


class _FakeAnthropicClient:
    def __init__(self, response: _FakeResponse) -> None:
        self.messages = _FakeMessages(response)


class _RaisingMessages:
    def create(self, **kwargs):
        raise anthropic.APIConnectionError(message="boom", request=None)


class _RaisingAnthropicClient:
    def __init__(self) -> None:
        self.messages = _RaisingMessages()


def test_generate_returns_concatenated_text_blocks() -> None:
    fake_client = _FakeAnthropicClient(
        _FakeResponse([_FakeTextBlock("Hello "), _FakeTextBlock("world")])
    )
    client = CommentaryClient(client=fake_client)

    result = client.generate("write something")

    assert result == "Hello world"


def test_generate_skips_non_text_blocks() -> None:
    fake_client = _FakeAnthropicClient(
        _FakeResponse([_FakeThinkingBlock(), _FakeTextBlock("final answer")])
    )
    client = CommentaryClient(client=fake_client)

    assert client.generate("prompt") == "final answer"


def test_generate_uses_default_model_and_effort() -> None:
    fake_client = _FakeAnthropicClient(_FakeResponse([_FakeTextBlock("ok")]))
    client = CommentaryClient(client=fake_client)

    client.generate("prompt")

    kwargs = fake_client.messages.last_kwargs
    assert kwargs["model"] == DEFAULT_MODEL
    assert kwargs["output_config"] == {"effort": DEFAULT_EFFORT}
    assert kwargs["messages"] == [{"role": "user", "content": "prompt"}]


def test_generate_honors_explicit_model_and_effort_overrides() -> None:
    fake_client = _FakeAnthropicClient(_FakeResponse([_FakeTextBlock("ok")]))
    client = CommentaryClient(client=fake_client)

    client.generate("prompt", model="claude-sonnet-5", effort="low", max_tokens=512)

    kwargs = fake_client.messages.last_kwargs
    assert kwargs["model"] == "claude-sonnet-5"
    assert kwargs["output_config"] == {"effort": "low"}
    assert kwargs["max_tokens"] == 512


def test_generate_raises_on_empty_text_response() -> None:
    fake_client = _FakeAnthropicClient(_FakeResponse([_FakeThinkingBlock()]))
    client = CommentaryClient(client=fake_client)

    with pytest.raises(CommentaryGenerationError):
        client.generate("prompt")


def test_generate_wraps_anthropic_api_errors() -> None:
    client = CommentaryClient(client=_RaisingAnthropicClient())

    with pytest.raises(CommentaryGenerationError):
        client.generate("prompt")
