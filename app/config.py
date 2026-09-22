from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Autonomous NOC"
    database_url: str = "sqlite:///./autonomous_noc.db"
    llm_provider: str = "disabled"
    llm_model: str = "gpt-5-mini"
    openai_api_key: str | None = None
    ollama_base_url: str = "http://ollama:11434"
    ollama_model: str = "qwen3.5:4b"
    auto_remediate: bool = False

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
