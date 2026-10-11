from pydantic_settings import BaseSettings
from typing import List

class Settings(BaseSettings):
    PROJECT_NAME: str = "HackCure API"
    ENVIRONMENT: str = "development"
    DATABASE_URL: str = "sqlite+aiosqlite:///./hackcure.db"
    SECRET_KEY: str = "hackcure-super-secure-production-ready-jwt-key-32chars-min"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    CORS_ORIGINS: List[str] = ["*"]
    AUTOMATION_API_KEY: str = "hackcure-automation-dev-key-2026"
    ANTHROPIC_API_KEY: str = ""
    CHAT_MODEL: str = "claude-sonnet-5"
    SAKINA_MODEL: str = "claude-sonnet-4-6"
    TRIAGE_MODEL: str = "claude-haiku-4-5-20251001"
    CHAT_MAX_TOKENS: int = 700
    CHAT_TIMEOUT_SECONDS: float = 45.0
    CHAT_RATE_LIMIT_PER_MINUTE: int = 12
    CHAT_N8N_WEBHOOK_BASE_URL: str = ""
    CHAT_N8N_CHAT_WEBHOOK_URL: str = ""
    CHAT_N8N_SHARED_SECRET: str = ""
    CHAT_DIAGNOSTIC_TOKEN: str = ""
    CHAT_DEFAULT_COUNTRY: str = "TN"
    PATIENT_TIMEZONE: str = "Africa/Tunis"

    class Config:
        env_file = ".env"
        extra = "allow"

settings = Settings()
