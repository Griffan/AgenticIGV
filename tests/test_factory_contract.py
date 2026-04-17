"""Test factory contract for LLM backend instantiation and BaseChatModel conformance."""

import os
import pytest
from unittest.mock import patch, MagicMock
from langchain_openai import ChatOpenAI
from langchain_core.language_models import BaseChatModel

from app.llm import get_llm_model, _create_openai_model, validate_llm_config


class TestFactoryContractOpenAI:
    """Test that get_llm_model() factory returns ChatOpenAI with correct contract."""

    def test_get_llm_model_returns_chatopenaI_instance_with_default_backend(self):
        """Test that get_llm_model() returns ChatOpenAI instance when LLM_BACKEND=openai (default)."""
        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "sk-test-key-12345",
                "LLM_BACKEND": "openai",
            },
        ):
            model = get_llm_model()
            assert isinstance(model, ChatOpenAI)

    def test_get_llm_model_returns_chatopenaI_instance_with_implicit_default(self):
        """Test that get_llm_model() returns ChatOpenAI when LLM_BACKEND is not set."""
        with patch.dict(
            os.environ,
            {"OPENAI_API_KEY": "sk-test-key-12345"},
            clear=False,
        ):
            # Ensure LLM_BACKEND is not set, so default is used
            env = os.environ.copy()
            env.pop("LLM_BACKEND", None)
            with patch.dict(os.environ, env, clear=True):
                model = get_llm_model()
                assert isinstance(model, ChatOpenAI)

    def test_chatopenaI_instance_conforms_to_basechatmodel_interface(self):
        """Test that ChatOpenAI instance has BaseChatModel interface (.invoke() method)."""
        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "sk-test-key-12345",
                "LLM_BACKEND": "openai",
            },
        ):
            model = get_llm_model()
            assert isinstance(model, BaseChatModel)
            assert hasattr(model, "invoke")
            assert callable(model.invoke)

    def test_custom_temperature_parameter_threaded_to_chatopenaI(self):
        """Test that LLM_TEMPERATURE env var is passed to ChatOpenAI constructor."""
        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "sk-test-key-12345",
                "LLM_TEMPERATURE": "0.7",
            },
        ):
            model = get_llm_model()
            assert model.temperature == 0.7

    def test_custom_max_tokens_parameter_threaded_to_chatopenaI(self):
        """Test that LLM_MAX_TOKENS env var is passed to ChatOpenAI constructor."""
        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "sk-test-key-12345",
                "LLM_MAX_TOKENS": "512",
            },
        ):
            model = get_llm_model()
            assert model.max_tokens == 512

    def test_custom_model_name_parameter_threaded_to_chatopenaI(self):
        """Test that LANGGRAPH_MODEL env var is passed to ChatOpenAI model parameter."""
        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "sk-test-key-12345",
                "LANGGRAPH_MODEL": "gpt-4",
            },
        ):
            model = get_llm_model()
            assert model.model_name == "gpt-4"

    def test_custom_base_url_parameter_threaded_to_chatopenaI(self):
        """Test that BASE_URL env var is passed to ChatOpenAI base_url parameter."""
        custom_url = "https://custom.openai.proxy.com/v1"
        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "sk-test-key-12345",
                "BASE_URL": custom_url,
            },
        ):
            model = get_llm_model()
            assert model.openai_api_base == custom_url

    def test_multiple_config_parameters_all_threaded(self):
        """Test that multiple config parameters are all applied together."""
        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "sk-test-key-12345",
                "LANGGRAPH_MODEL": "gpt-4-turbo",
                "BASE_URL": "https://custom.api.com/v1",
                "LLM_TEMPERATURE": "0.5",
                "LLM_MAX_TOKENS": "256",
            },
        ):
            model = get_llm_model()
            assert model.model_name == "gpt-4-turbo"
            assert model.openai_api_base == "https://custom.api.com/v1"
            assert model.temperature == 0.5
            assert model.max_tokens == 256


class TestFactoryErrorHandling:
    """Test error handling and validation in the factory."""

    def test_missing_openai_api_key_raises_value_error(self):
        """Test that missing OPENAI_API_KEY raises ValueError."""
        with patch.dict(
            os.environ,
            {"LLM_BACKEND": "openai"},
            clear=True,
        ):
            with pytest.raises(ValueError) as exc_info:
                get_llm_model()
            assert "OPENAI_API_KEY" in str(exc_info.value)

    def test_missing_openai_api_key_error_message_directs_user(self):
        """Test that missing OPENAI_API_KEY error message is actionable."""
        with patch.dict(
            os.environ,
            {"LLM_BACKEND": "openai"},
            clear=True,
        ):
            with pytest.raises(ValueError) as exc_info:
                get_llm_model()
            error_msg = str(exc_info.value)
            # Should mention that API key is required
            assert "OPENAI_API_KEY" in error_msg
            # Should indicate OpenAI backend is selected
            assert "OpenAI" in error_msg or "openai" in error_msg

    def test_invalid_llm_backend_raises_value_error(self):
        """Test that invalid LLM_BACKEND value raises ValueError."""
        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "sk-test-key-12345",
                "LLM_BACKEND": "invalid-backend",
            },
        ):
            with pytest.raises(ValueError) as exc_info:
                get_llm_model()
            assert "Invalid LLM_BACKEND" in str(exc_info.value)
            assert "invalid-backend" in str(exc_info.value)

    def test_invalid_temperature_format_raises_error(self):
        """Test that invalid temperature value raises an error."""
        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "sk-test-key-12345",
                "LLM_TEMPERATURE": "not-a-number",
            },
        ):
            with pytest.raises(ValueError):
                get_llm_model()

    def test_invalid_max_tokens_format_raises_error(self):
        """Test that invalid max_tokens value raises an error."""
        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "sk-test-key-12345",
                "LLM_MAX_TOKENS": "not-a-number",
            },
        ):
            with pytest.raises(ValueError):
                get_llm_model()


class TestValidateLLMConfig:
    """Test the validate_llm_config() function for startup validation."""

    def test_validate_llm_config_openai_success(self):
        """Test that validate_llm_config() returns correct backend and model info for OpenAI."""
        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "sk-test-key-12345",
                "LLM_BACKEND": "openai",
                "LANGGRAPH_MODEL": "gpt-4",
                "BASE_URL": "https://api.openai.com/v1",
            },
        ):
            backend_name, model_info = validate_llm_config()
            assert backend_name == "openai"
            assert "gpt-4" in model_info
            assert "api.openai.com" in model_info

    def test_validate_llm_config_missing_openai_key_raises_error(self):
        """Test that validate_llm_config() raises error when OpenAI API key is missing."""
        with patch.dict(
            os.environ,
            {"LLM_BACKEND": "openai"},
            clear=True,
        ):
            with pytest.raises(ValueError) as exc_info:
                validate_llm_config()
            error_msg = str(exc_info.value)
            assert "OPENAI_API_KEY" in error_msg
            # Should provide actionable guidance
            assert ".env" in error_msg or "Set" in error_msg

    def test_validate_llm_config_with_default_backend(self):
        """Test that validate_llm_config() uses 'openai' as default backend."""
        with patch.dict(
            os.environ,
            {"OPENAI_API_KEY": "sk-test-key-12345"},
            clear=False,
        ):
            env = os.environ.copy()
            env.pop("LLM_BACKEND", None)
            with patch.dict(os.environ, env, clear=True):
                backend_name, model_info = validate_llm_config()
                assert backend_name == "openai"


class TestDefaultValues:
    """Test that factory applies correct default values."""

    def test_default_temperature_is_zero(self):
        """Test that default LLM_TEMPERATURE is 0."""
        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "sk-test-key-12345",
                "LLM_TEMPERATURE": "",  # Empty string should be treated as missing
            },
        ):
            # Need to unset it completely for default to apply
            env = os.environ.copy()
            env["OPENAI_API_KEY"] = "sk-test-key-12345"
            env.pop("LLM_TEMPERATURE", None)
            with patch.dict(os.environ, env, clear=True):
                model = get_llm_model()
                assert model.temperature == 0

    def test_default_model_name_is_gpt4o_mini(self):
        """Test that default LANGGRAPH_MODEL is 'gpt-4o-mini'."""
        with patch.dict(
            os.environ,
            {"OPENAI_API_KEY": "sk-test-key-12345"},
            clear=False,
        ):
            env = os.environ.copy()
            env["OPENAI_API_KEY"] = "sk-test-key-12345"
            env.pop("LANGGRAPH_MODEL", None)
            with patch.dict(os.environ, env, clear=True):
                model = get_llm_model()
                assert model.model_name == "gpt-4o-mini"

    def test_default_base_url_is_openai_api(self):
        """Test that default BASE_URL is 'https://api.openai.com/v1'."""
        with patch.dict(
            os.environ,
            {"OPENAI_API_KEY": "sk-test-key-12345"},
            clear=False,
        ):
            env = os.environ.copy()
            env["OPENAI_API_KEY"] = "sk-test-key-12345"
            env.pop("BASE_URL", None)
            with patch.dict(os.environ, env, clear=True):
                model = get_llm_model()
                assert model.openai_api_base == "https://api.openai.com/v1"

    def test_default_max_tokens_is_none(self):
        """Test that max_tokens defaults to None when LLM_MAX_TOKENS is not set."""
        with patch.dict(
            os.environ,
            {"OPENAI_API_KEY": "sk-test-key-12345"},
            clear=False,
        ):
            env = os.environ.copy()
            env["OPENAI_API_KEY"] = "sk-test-key-12345"
            env.pop("LLM_MAX_TOKENS", None)
            with patch.dict(os.environ, env, clear=True):
                model = get_llm_model()
                # max_tokens should be None, not set or 0
                assert model.max_tokens is None
