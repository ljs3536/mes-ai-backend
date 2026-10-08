from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "mysql+pymysql://mes:mes@localhost:3306/mes?charset=utf8mb4"
    cors_origins: list[str] = ["http://localhost:3000"]
    seed_demo: bool = True
    machine_api_key: str = "dev-machine-key"
    machine_offline_after_seconds: int = 10
    timezone: str = "Asia/Seoul"


@lru_cache
def get_settings() -> Settings:
    return Settings()
