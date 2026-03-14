from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import os

from pydantic import AliasChoices, Field
from dotenv import load_dotenv
from pydantic_settings import BaseSettings


ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(ENV_FILE)


class Settings(BaseSettings):
    google_places_api_key: str = Field(
        default_factory=lambda: (
            os.getenv("google_places_api_key")
            or os.getenv("google_map_api_key")
            or os.getenv("GOOGLE_PLACES_API_KEY")
            or os.getenv("GOOGLE_MAP_API_KEY")
            or ""
        ),
        validation_alias=AliasChoices("google_places_api_key", "google_map_api_key"),
    )
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    usda_api_key: str = ""
    user_profile_storage_path: str = "./data/user_profiles.json"
    restaurant_cache_ttl: int = 300
    restaurant_cache_maxsize: int = 1000

    model_config = {
        "env_file": str(ENV_FILE),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


@lru_cache
def get_settings() -> Settings:
    return Settings()
