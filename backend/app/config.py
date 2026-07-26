"""Central config, loaded once from .env.

Kept deliberately tiny: this is a single-user local app, so there's no
per-request auth/config resolution to worry about -- just process-wide
settings loaded from environment variables.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ebird_api_key: str = ""

    flickr_api_key: str = ""
    flickr_api_secret: str = ""
    flickr_oauth_token: str = ""
    flickr_oauth_token_secret: str = ""
    flickr_user_id: str = ""

    # Strategy B (AI-assisted species suggestion) -- see
    # app/services/species_classifier.py. Optional: the app works fine
    # without it, "Suggest species" just won't be available in the UI.
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5"

    database_url: str = "sqlite:///./birdtrip.db"


settings = Settings()