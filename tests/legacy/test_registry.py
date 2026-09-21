"""Tests for the supported-model registry."""

import pytest

from pentestgpt_legacy.llm.registry import (
    MODELS,
    PROVIDERS,
    all_model_ids,
    models_by_provider,
    resolve,
)

pytestmark = pytest.mark.unit


def test_resolve_known_model() -> None:
    spec = resolve("gpt-5.5")
    assert spec is not None
    assert spec.provider == "openai"
    assert spec.api_id == "gpt-5.5"  # api_id defaults to id


def test_resolve_alias() -> None:
    spec = resolve("claude-haiku-4-5")
    assert spec is not None
    assert spec.id == "claude-haiku-4-5-20251001"


def test_resolve_ollama_dynamic() -> None:
    spec = resolve("ollama:qwen3")
    assert spec is not None
    assert spec.provider == "ollama"
    assert spec.api_id == "qwen3"


def test_resolve_ollama_empty_is_none() -> None:
    assert resolve("ollama:") is None


def test_resolve_anonrouter_dynamic() -> None:
    spec = resolve("anonrouter:meta-llama/llama-3.3-70b")
    assert spec is not None
    assert spec.provider == "anonrouter"
    # The nested router id is sent on the wire verbatim, prefix stripped.
    assert spec.api_id == "meta-llama/llama-3.3-70b"


def test_resolve_anonrouter_preserves_case_and_nesting() -> None:
    # Synthetic casing verifies that the resolver does not normalize the
    # account-provided catalog ID before sending it to AnonRouter.
    spec = resolve("anonrouter:Qwen/Qwen3-235B-A22B")
    assert spec is not None
    assert spec.api_id == "Qwen/Qwen3-235B-A22B"


def test_resolve_anonrouter_empty_is_none() -> None:
    assert resolve("anonrouter:") is None
    assert resolve("anonrouter:   ") is None


def test_resolve_unknown_is_none() -> None:
    assert resolve("definitely-not-a-model") is None


def test_anonrouter_provider_registered() -> None:
    info = PROVIDERS["anonrouter"]
    assert info.kind == "openai"
    assert info.base_url == "https://api.anonrouter.ai/v1"
    assert info.env == "ANONROUTER_API_KEY"
    assert info.requires_key is True


def test_anonrouter_pins_no_static_models() -> None:
    # The router's catalog changes, so no model subset is checked in.
    assert all(spec.provider != "anonrouter" for spec in MODELS.values())


def test_all_model_ids_unique_and_nonempty() -> None:
    ids = all_model_ids()
    assert ids
    assert len(ids) == len(set(ids))


def test_every_model_provider_is_registered() -> None:
    for spec in MODELS.values():
        assert spec.provider in PROVIDERS


def test_api_id_defaults_to_id() -> None:
    for spec in MODELS.values():
        assert spec.api_id  # never empty


def test_models_by_provider_covers_all() -> None:
    grouped = models_by_provider()
    total = sum(len(specs) for specs in grouped.values())
    assert total == len(MODELS)
    # current flagship providers must be present
    for provider in ("openai", "anthropic", "gemini", "deepseek"):
        assert provider in grouped
