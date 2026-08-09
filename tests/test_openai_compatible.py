"""OpenAI 兼容接口的流式事件回归测试。"""

import pytest

from backend.llm import ModelProviderError
from backend.providers.openai_compatible import OpenAICompatibleClient


def test_stream_choice_ignores_empty_usage_frame() -> None:
    event = {
        "choices": [],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20},
    }

    assert OpenAICompatibleClient._stream_choice(event) is None


def test_stream_choice_returns_normal_delta() -> None:
    choice = {"delta": {"content": "你好"}, "finish_reason": None}

    assert OpenAICompatibleClient._stream_choice({"choices": [choice]}) == choice


def test_stream_choice_surfaces_provider_error() -> None:
    with pytest.raises(ModelProviderError, match="配额不足"):
        OpenAICompatibleClient._stream_choice(
            {"error": {"message": "配额不足"}}
        )
