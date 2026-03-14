from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    google_places_api_key: str = ""
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    usda_api_key: str = ""
    user_profile_storage_path: str = "./data/user_profiles.json"
    restaurant_cache_ttl: int = 300
    restaurant_cache_maxsize: int = 1000

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
