"""Tests for the LiteLLM provider integration."""

import pytest

from pentestgpt_legacy.llm import factory
from pentestgpt_legacy.llm.config import LLMSettings
from pentestgpt_legacy.llm.factory import get_client
from pentestgpt_legacy.llm.providers import LiteLLMProvider
from pentestgpt_legacy.llm.registry import PROVIDERS, resolve

pytestmark = pytest.mark.unit


def _settings(**kwargs: str) -> LLMSettings:
    return LLMSettings(_env_file=None, **kwargs)


def test_litellm_provider_in_registry() -> None:
    assert "litellm" in PROVIDERS
    assert PROVIDERS["litellm"].kind == "litellm"
    assert PROVIDERS["litellm"].requires_key is False


def test_resolve_litellm_dynamic() -> None:
    spec = resolve("litellm:azure/gpt-4")
    assert spec is not None
    assert spec.provider == "litellm"
    assert spec.api_id == "azure/gpt-4"
    assert spec.tier == "gateway"


def test_resolve_litellm_bedrock() -> None:
    spec = resolve("litellm:bedrock/anthropic.claude-v2")
    assert spec is not None
    assert spec.api_id == "bedrock/anthropic.claude-v2"


def test_resolve_litellm_empty_is_none() -> None:
    assert resolve("litellm:") is None


def test_get_client_litellm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(factory, "get_settings", lambda: _settings())
    client = get_client("litellm:azure/gpt-4")
    assert isinstance(client.provider, LiteLLMProvider)
    assert client.spec.api_id == "azure/gpt-4"


def test_get_client_litellm_with_proxy_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        factory,
        "get_settings",
        lambda: _settings(litellm_api_key="sk-proxy", litellm_base_url="http://proxy:4000"),
    )
    client = get_client("litellm:gpt-4")
    assert client.provider.api_key == "sk-proxy"
    assert client.provider.base_url == "http://proxy:4000"
