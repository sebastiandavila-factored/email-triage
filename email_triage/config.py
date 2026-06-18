from __future__ import annotations

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_INSECURE_SESSION_SECRET = "change-me-in-production"


class Settings(BaseSettings):
    groq_api_key: str
    groq_model: str = "llama-3.3-70b-versatile"
    api_key: str
    logfire_sample_rate: float = 1.0
    logfire_environment: str = "dev"
    database_url: str | None = None  # postgresql+asyncpg://user:pass@host:5432/dbname

    # Google OAuth2 — required only when Google SSO is used
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/auth/callback"
    session_secret: str = _INSECURE_SESSION_SECRET
    access_token_expire_minutes: int = 30
    frontend_url: str = "http://localhost:5173"
    bcrypt_rounds: int = 12
    # Browser origins allowed to call the API cross-origin (CORS), comma-separated.
    # Empty in dev (Vite proxy → same-origin). In prod set the frontend origin(s),
    # e.g. CORS_ORIGINS=https://email-triage.vercel.app
    # A plain string (not list[str]) so an env value can't fail JSON parsing and
    # crash startup; parsing is tolerant of stray brackets/quotes.
    cors_origins: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def cors_origins_list(self) -> list[str]:
        # Tolerant parse: comma-separated, ignoring stray brackets/quotes/space
        # so a value like `["https://a"]` or `https://a, https://b` both work.
        parts = (o.strip().strip("\"'[] ") for o in self.cors_origins.split(","))
        return [p for p in parts if p]

    @model_validator(mode="after")
    def _reject_insecure_prod_secret(self) -> Settings:
        # Forging a JWT for any user only needs the signing secret, so the
        # placeholder must never reach production.
        if (
            self.logfire_environment == "production"
            and self.session_secret == _INSECURE_SESSION_SECRET
        ):
            raise ValueError("SESSION_SECRET must be set to a real value in production")
        return self
