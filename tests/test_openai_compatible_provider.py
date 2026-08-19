"""Tests for the generic ``openai_compatible`` provider (#77 / #81).

A pass-through for any relay/gateway that speaks the OpenAI Chat Completions
API (9Router, AI Router, self-hosted proxy): the user supplies base_url +
model + a generic API key, with no hard-coded vendor defaults.
"""

import pytest

from tradingagents.llm_clients.factory import _OPENAI_COMPATIBLE, create_llm_client
from tradingagents.llm_clients.openai_client import NormalizedChatOpenAI, OpenAIClient


@pytest.mark.unit
class TestFactoryRouting:
    def test_openai_compatible_is_routed_to_openai_client(self):
        assert "openai_compatible" in _OPENAI_COMPATIBLE
        client = create_llm_client(
            "openai_compatible", "any-model", base_url="https://relay.example/v1"
        )
        assert isinstance(client, OpenAIClient)
        assert client.provider == "openai_compatible"


@pytest.mark.unit
class TestOpenAICompatibleClient:
    def test_missing_base_url_raises(self, monkeypatch):
        monkeypatch.setenv("OPENAI_COMPATIBLE_API_KEY", "k")
        client = OpenAIClient("m", base_url=None, provider="openai_compatible")
        with pytest.raises(RuntimeError, match="base_url"):
            client.get_llm()

    def test_missing_key_raises(self, monkeypatch):
        monkeypatch.delenv("OPENAI_COMPATIBLE_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        client = OpenAIClient("m", base_url="https://relay.example/v1", provider="openai_compatible")
        with pytest.raises(RuntimeError, match="API Key"):
            client.get_llm()

    def test_uses_dedicated_env_key_and_base_url(self, monkeypatch):
        monkeypatch.setenv("OPENAI_COMPATIBLE_API_KEY", "relay-key")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        client = OpenAIClient(
            "my-model", base_url="https://relay.example/v1", provider="openai_compatible"
        )
        llm = client.get_llm()
        # Chat Completions (not OpenAI's Responses API) for max compatibility.
        assert isinstance(llm, NormalizedChatOpenAI)
        assert str(llm.openai_api_base) == "https://relay.example/v1"

    def test_falls_back_to_openai_api_key(self, monkeypatch):
        monkeypatch.delenv("OPENAI_COMPATIBLE_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "fallback-key")
        client = OpenAIClient(
            "my-model", base_url="https://relay.example/v1", provider="openai_compatible"
        )
        # Must not raise — the OPENAI_API_KEY fallback supplies the credential.
        assert client.get_llm() is not None

    def test_custom_model_does_not_warn(self, monkeypatch, recwarn):
        monkeypatch.setenv("OPENAI_COMPATIBLE_API_KEY", "k")
        client = OpenAIClient(
            "totally-custom-model", base_url="https://relay.example/v1",
            provider="openai_compatible",
        )
        client.get_llm()
        assert not [w for w in recwarn if "not in the known model list" in str(w.message)]
