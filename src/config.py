"""Runtime configuration.

Provider / model / pricing all come from .env — never hardcoded (spec 4.1).
Env vars are provider-scoped: LLM_PROVIDER selects a block of
<PROVIDER>_MODEL / <PROVIDER>_API_KEY / <PROVIDER>_BASE_URL variables
(e.g. DEEPSEEK_*, OPENAI_*, OPENROUTE_*). Every provider is assumed
OpenAI-compatible, so no provider-specific SDK is needed.
"""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

# Fallback base URLs for providers whose endpoint is fixed and public.
_DEFAULT_BASE_URLS = {
    "deepseek": "https://api.deepseek.com",
    "openroute": "https://openrouter.ai/api/v1",
    "openai": None,  # langchain-openai default
}


@dataclass(frozen=True)
class Settings:
    provider: str
    model: str
    api_key: str
    base_url: str | None
    max_tokens: int
    temperature: float
    tavily_api_key: str
    # USD per 1M tokens, used only for the end-of-run cost estimate
    price_input_per_m: float
    price_output_per_m: float


def load_settings() -> Settings:
    provider = os.getenv("LLM_PROVIDER", "deepseek").strip().lower()
    prefix = provider.upper()
    model = os.getenv(f"{prefix}_MODEL", "").strip()
    api_key = os.getenv(f"{prefix}_API_KEY", "").strip()
    base_url = os.getenv(f"{prefix}_BASE_URL", "").strip() or _DEFAULT_BASE_URLS.get(provider)
    if not model:
        raise RuntimeError(f"{prefix}_MODEL is not set in .env (LLM_PROVIDER={provider})")
    if not api_key:
        raise RuntimeError(f"{prefix}_API_KEY is not set in .env (LLM_PROVIDER={provider})")
    return Settings(
        provider=provider,
        model=model,
        api_key=api_key,
        base_url=base_url,
        max_tokens=int(os.getenv("MAX_TOKENS_PER_CALL", "4096")),
        temperature=float(os.getenv("LLM_TEMPERATURE", "0.3")),
        tavily_api_key=os.getenv("TAVILY_API_KEY", "").strip(),
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
