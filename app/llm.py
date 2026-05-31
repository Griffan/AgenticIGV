"""
LLM factory abstraction layer for selecting between OpenAI and AWS Bedrock backends.
Provides get_llm_model() function that returns a BaseChatModel instance.
"""

import os
from typing import Any, Dict, Optional

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI
from pydantic import SecretStr


def _env_int(name: str, default: int) -> int:
    """Read an int env var, treating unset/empty/whitespace as the default."""
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw.strip())
    except ValueError as e:
        raise ValueError(
            f"Environment variable {name}={raw!r} is not a valid integer"
        ) from e


def _env_float(name: str, default: float) -> float:
    """Read a float env var, treating unset/empty/whitespace as the default."""
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw.strip())
    except ValueError as e:
        raise ValueError(
            f"Environment variable {name}={raw!r} is not a valid number"
        ) from e


def _env_optional_int(name: str) -> Optional[int]:
    """Read an optional int env var, returning None when unset/empty."""
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return None
    try:
        return int(raw.strip())
    except ValueError as e:
        raise ValueError(
            f"Environment variable {name}={raw!r} is not a valid integer"
        ) from e


def _create_openai_model() -> BaseChatModel:
    """
    Create and return an OpenAI ChatModel instance.
    
    Requires environment variables:
    - OPENAI_API_KEY: OpenAI API key
    - LANGGRAPH_MODEL: Model name (default: "gpt-4o-mini")
    - BASE_URL: API base URL (default: "https://api.openai.com/v1")
    - LLM_TEMPERATURE: Temperature for generation (default: 0)
    - LLM_MAX_TOKENS: Max tokens per response (optional)
    
    Returns:
        ChatOpenAI: Configured OpenAI chat model
        
    Raises:
        ValueError: If required environment variables are missing
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OpenAI backend selected but OPENAI_API_KEY is not set")
    
    model_name = os.getenv("LANGGRAPH_MODEL", "gpt-4o-mini")
    base_url = os.getenv("BASE_URL", "https://api.openai.com/v1")
    temperature = _env_float("LLM_TEMPERATURE", 0.0)
    max_tokens = _env_optional_int("LLM_MAX_TOKENS")
    
    kwargs = {
        "model": model_name,
        "temperature": temperature,
        "base_url": base_url,
        "api_key": SecretStr(api_key),
    }
    
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    
    return ChatOpenAI(**kwargs)


def _create_bedrock_model() -> BaseChatModel:
    """
    Create and return an AWS Bedrock ChatModel instance.
    
    Requires environment variables:
    - AWS_BEDROCK_MODEL: Model ID on Bedrock (e.g., "anthropic.claude-3-sonnet-20240229-v1:0")
    - AWS_REGION: AWS region (default: "us-east-1")
    - AWS_ACCESS_KEY_ID: AWS access key (optional, uses boto3 default chain if not set)
    - AWS_SECRET_ACCESS_KEY: AWS secret key (optional, uses boto3 default chain if not set)
    - LLM_TEMPERATURE: Temperature for generation (default: 0)
    - LLM_MAX_TOKENS: Max tokens per response (default: 1024)
    
    Returns:
        BedrockChat: Configured Bedrock chat model
        
    Raises:
        ValueError: If required environment variables are missing or langchain-aws not installed
        ImportError: If langchain-aws is not available
    """
    try:
        from langchain_aws import ChatBedrock
    except ImportError as e:
        raise ImportError(
            "langchain-aws is not installed. Install it with: pip install langchain-aws"
        ) from e
    
    model_id = os.getenv("AWS_BEDROCK_MODEL")
    if not model_id:
        raise ValueError(
            "Bedrock backend selected but AWS_BEDROCK_MODEL is not set. "
            "Example: 'anthropic.claude-3-sonnet-20240229-v1:0'"
        )
    
    region = os.getenv("AWS_REGION", "us-east-1")
    temperature = _env_float("LLM_TEMPERATURE", 0.0)
    max_tokens = _env_int("LLM_MAX_TOKENS", 1024)
    
    # Bedrock will use boto3's default credential chain if credentials are not provided.
    # Only forward explicit AWS_* values when actually set so we don't override the chain
    # with None / empty strings.
    kwargs: Dict[str, Any] = {
        "model_id": model_id,
        "region_name": region,
        "model_kwargs": {
            "temperature": temperature,
            "max_tokens": max_tokens,
        },
    }

    access_key = (os.getenv("AWS_ACCESS_KEY_ID") or "").strip()
    secret_key = (os.getenv("AWS_SECRET_ACCESS_KEY") or "").strip()
    session_token = (os.getenv("AWS_SESSION_TOKEN") or "").strip()
    if access_key:
        kwargs["aws_access_key_id"] = access_key
    if secret_key:
        kwargs["aws_secret_access_key"] = secret_key
    if session_token:
        kwargs["aws_session_token"] = session_token

    return ChatBedrock(**kwargs)


def get_llm_model() -> BaseChatModel:
    """
    Factory function to get an LLM model instance based on LLM_BACKEND configuration.
    
    Environment variables:
    - LLM_BACKEND: Backend selection ("openai" or "bedrock", default: "openai")
    - OPENAI_API_KEY: Required for OpenAI backend
    - AWS_BEDROCK_MODEL: Required for Bedrock backend
    
    Returns:
        BaseChatModel: Instance of ChatOpenAI or ChatBedrock
        
    Raises:
        ValueError: If LLM_BACKEND is invalid or required env vars are missing
        ImportError: If langchain-aws not installed for Bedrock backend
    """
    backend = os.getenv("LLM_BACKEND", "openai").lower()
    
    if backend == "openai":
        return _create_openai_model()
    elif backend == "bedrock":
        return _create_bedrock_model()
    else:
        raise ValueError(
            f"Invalid LLM_BACKEND: {backend}. Must be 'openai' or 'bedrock'."
        )


def validate_llm_config() -> tuple[str, str]:
    """
    Validate LLM configuration at startup and return backend name and model info.
    
    This function validates:
    - LLM_BACKEND is set and valid
    - Required credentials for the selected backend are present
    - Required packages are installed
    
    Returns:
        tuple[str, str]: (backend_name, model_info) for logging
        
    Raises:
        ValueError: If configuration is invalid
        ImportError: If required packages are missing
    """
    backend = os.getenv("LLM_BACKEND", "openai").lower()
    
    if backend == "openai":
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError(
                "OpenAI backend selected but OPENAI_API_KEY is not set. "
                "Set OPENAI_API_KEY in your .env file."
            )
        model_name = os.getenv("LANGGRAPH_MODEL", "gpt-4o-mini")
        base_url = os.getenv("BASE_URL", "https://api.openai.com/v1")
        return ("openai", f"Model: {model_name}, Base URL: {base_url}")
    
    elif backend == "bedrock":
        # Check if langchain-aws is installed
        try:
            import langchain_aws  # noqa: F401
        except ImportError as e:
            raise ImportError(
                "AWS Bedrock backend selected but langchain-aws is not installed. "
                "Install it with: pip install langchain-aws"
            ) from e
        
        model_id = os.getenv("AWS_BEDROCK_MODEL")
        if not model_id:
            raise ValueError(
                "AWS Bedrock backend selected but AWS_BEDROCK_MODEL is not set. "
                "Example: 'anthropic.claude-3-sonnet-20240229-v1:0'"
            )
        
        region = os.getenv("AWS_REGION", "us-east-1")
        return ("bedrock", f"Model ID: {model_id}, Region: {region}")
    
    else:
        raise ValueError(
            f"Invalid LLM_BACKEND: {backend}. Must be 'openai' or 'bedrock'."
        )
