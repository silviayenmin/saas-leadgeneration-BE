import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "MapFlow AI API"
    VERSION: str = "1.0.0"
    API_PREFIX: str = "/api"
    
    PORT: int = 8000
    HOST: str = "0.0.0.0"
    DEBUG: bool = True

    MONGODB_URI: str = os.getenv("MONGODB_URI", "mongodb://localhost:27017/mapflow_ai")
    DATABASE_NAME: str = os.getenv("DATABASE_NAME", "mapflow_ai")
    JSON_DB_FALLBACK: bool = False


    JWT_SECRET: str = os.getenv("JWT_SECRET", "super_secret_jwt_key_mapflow_ai_2026_change_in_production")
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days

    GOOGLE_PLACES_API_KEY: str = os.getenv("GOOGLE_PLACES_API_KEY", "")
    SERPER_API_KEY: str = os.getenv("SERPER_API_KEY", "")
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

    # Plan Credit Limits
    FREE_CREDITS: int = 25
    STARTER_CREDITS: int = 500
    AGENCY_PRO_CREDITS: int = 3000

    # Credit Costs
    COST_MAP_SEARCH: int = 1
    COST_REVEAL_EMAIL: int = 1
    COST_AI_PITCH: int = 2
    COST_BULK_SCAN: int = 5

    class Config:
        case_sensitive = True

settings = Settings()