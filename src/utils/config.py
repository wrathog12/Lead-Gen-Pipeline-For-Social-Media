"""
Config — Centralized configuration management.

Loads settings from .env file and provides typed access
to all configuration values used across the application.
"""

from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # LLM
    gemini_api_key: str = ""

    # Reddit
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_username: str = ""
    reddit_password: str = ""
    reddit_user_agent: str = "LeadGenPoC/0.1"

    # YouTube
    youtube_api_key: str = ""
    youtube_oauth_token: str = ""  # OAuth 2.0 token for posting (API key is read-only)

    # X / Twitter
    x_bearer_token: str = ""
    x_api_key: str = ""
    x_api_secret: str = ""
    x_access_token: str = ""
    x_access_secret: str = ""

    # Application
    tier2_threshold: int = 85
    dedup_ttl_hours: int = 72
    database_url: str = "sqlite:///./data/leadgen.db"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


# Singleton instance
settings = Settings()
