import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    PROJECT_NAME: str = "MapFlow AI API"
    VERSION: str = "1.0.0"
    API_PREFIX: str = "/api"
    
    PORT: int = 8000
    HOST: str = "0.0.0.0"
    DEBUG: bool = True

    MONGODB_URI: str = "mongodb://localhost:27017/mapflow_ai"
    DATABASE_NAME: str = "mapflow_ai"
    JSON_DB_FALLBACK: bool = False

    JWT_SECRET: str = "super_secret_jwt_key_mapflow_ai_2026_change_in_production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days

    GOOGLE_PLACES_API_KEY: str = ""
    SERPER_API_KEY: str = ""
    GROQ_API_KEY: str = ""
    OLLAMA_BASE_URL: str = "http://localhost:11434"

    # SMTP Outreach & Email Verification
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""

    # Plan Credit Limits
    FREE_CREDITS: int = 25
    STARTER_CREDITS: int = 500
    AGENCY_PRO_CREDITS: int = 3000

    # Credit Costs
    COST_MAP_SEARCH: int = 1
    COST_REVEAL_EMAIL: int = 1
    COST_AI_PITCH: int = 2
    COST_BULK_SCAN: int = 5

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True
    )

settings = Settings()