from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # Database
    database_url: str

    # Brainbase API
    brainbase_api_key: str
    brainbase_base_url: str = "https://api.usebrainbase.com"

    # App
    billing_timezone: str = "America/New_York"
    secret_key: str = "change-me-in-production"
    environment: str = "development"

    # Azure AD (production only)
    azure_tenant_id: Optional[str] = None
    azure_client_id: Optional[str] = None

    # Freshness thresholds (seconds)
    freshness_voice_analysis: int = 900    # 15 min
    freshness_call_logs: int = 3600        # 1 hour
    freshness_runtime_errors: int = 300    # 5 min
    freshness_echo: int = 3600             # 1 hour

    # Alerting
    slack_webhook_url: Optional[str] = None
    pagerduty_routing_key: Optional[str] = None

    # Cache
    cache_ttl_seconds: int = 300
    redis_url: Optional[str] = None

    class Config:
        env_file = ".env"


settings = Settings()
