from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    database_url: str = "sqlite+aiosqlite:///./gyn_kol.db"

    # Redis
    redis_url: str = "redis://localhost:6379"

    # External APIs
    ncbi_api_key: str = ""
    crossref_email: str = ""
    google_maps_api_key: str = ""

    # AI
    anthropic_api_key: str = ""


settings = Settings()
