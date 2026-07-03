"""Runtime configuration.

Provider / model / pricing all come from .env — never hardcoded (spec 4.1).
The API is assumed OpenAI-compatible, so DeepSeek needs no dedicated SDK.
"""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    provider: str
    model: str
    api_key: str
    base_url: str
    max_tokens: int
    temperature: float
    # USD per 1M tokens, used only for the end-of-run cost estimate
    price_input_per_m: float
    price_output_per_m: float


def load_settings() -> Settings:
    return Settings(
        provider=os.getenv("LLM_PROVIDER", "deepseek"),
        model=os.getenv("LLM_MODEL", "deepseek-chat"),
        api_key=os.getenv("DEEPSEEK_API_KEY", ""),
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        max_tokens=int(os.getenv("MAX_TOKENS_PER_CALL", "4096")),
        temperature=float(os.getenv("LLM_TEMPERATURE", "0.3")),
        price_input_per_m=float(os.getenv("PRICE_INPUT_PER_M", "0.27")),
        price_output_per_m=float(os.getenv("PRICE_OUTPUT_PER_M", "1.10")),
    )


def get_chat_model(settings: Settings | None = None, **overrides):
    """Build a ChatOpenAI client pointed at the configured provider."""
    from langchain_openai import ChatOpenAI

    s = settings or load_settings()
    kwargs: dict = dict(
        model=s.model,
        api_key=s.api_key,
        base_url=s.base_url,
        max_tokens=s.max_tokens,
        temperature=s.temperature,
    )
    kwargs.update(overrides)
    return ChatOpenAI(**kwargs)
