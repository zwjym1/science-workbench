from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore', env_ignore_empty=True)
    database_url: str = 'sqlite:///./workbench.db'
    admin_password: str = Field(min_length=12)
    session_secret: str = Field(min_length=32)
    cookie_secure: bool = True
    session_hours: int = 24
    analysis_provider: str = 'openai-compatible'
    analysis_model: str = ''
    analysis_base_url: str = ''
    analysis_api_key: str = ''
    analysis_timeout: int = Field(default=90, ge=5, le=300)
    analysis_max_output_tokens: int = Field(default=4000, ge=256, le=16000)
    analysis_input_price_per_million: float | None = Field(default=None, ge=0)
    analysis_output_price_per_million: float | None = Field(default=None, ge=0)
    analysis_budget_per_job: float = Field(default=0.25, gt=0)
    analysis_daily_budget: float = Field(default=2, gt=0)


@lru_cache
def settings():
    return Settings()
