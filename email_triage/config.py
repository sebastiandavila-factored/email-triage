from __future__ import annotations

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_INSECURE_SESSION_SECRET = "change-me-in-production"

# Single source of truth for the default Groq model. Overridable per-environment
# via GROQ_MODEL; imported by services/evals so the default can never drift.
DEFAULT_GROQ_MODEL = "qwen/qwen3.6-27b"


class Settings(BaseSettings):
    groq_api_key: str
    groq_model: str = DEFAULT_GROQ_MODEL
    api_key: str
    # Logfire Prompt Management label to resolve the triage system prompt from.
    # The in-code SYSTEM_PROMPT is the fallback if Logfire has no managed variable.
    prompt_label: str = "production"
    logfire_sample_rate: float = 1.0
    logfire_environment: str = "dev"
    # Read token (scope `project:read`) for the trace-debug chat (Plan 31). Lives
    # ONLY in the backend: it is project-wide (sees every tenant's traces), so it must
    # never reach the client — per-org isolation is enforced by our SQL, not the token.
    # Absent → the chat endpoint returns 503 (feature not configured).
    logfire_read_token: str | None = None
    # Optional override for the Logfire read API base URL; None → derived from the read
    # token's region (US/EU) automatically, so it normally needs no configuration.
    logfire_read_base_url: str | None = None

    # Online evals on live /triage. Off by default; opt-in per env. sample_rate keeps the
    # critical path cheap (evaluators dispatch asynchronously after the run, non-blocking).
    online_eval_enabled: bool = False
    online_eval_sample_rate: float = 0.05
    online_eval_max_concurrency: int = 2
    database_url: str | None = None  # postgresql+asyncpg://user:pass@host:5432/dbname

    # Google OAuth2 — required only when Google SSO is used
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/auth/callback"

    # Gmail ingestion (Plan 36) — connect a mailbox to pull the day's emails. Reuses
    # google_client_id/secret with a *separate* redirect URI (register it in Google
    # Cloud Console). gmail_token_enc_key is a Fernet key (TokenCipher.generate_key());
    # without it the Gmail endpoints return 503 (feature not configured). gmail_sync_max_results
    # bounds how many emails a single sync triages (Plan 37) — kept low (15) so a full sync
    # stays well under Cloudflare's ~100s edge timeout even at the default concurrency (Plan 41).
    gmail_redirect_uri: str = "http://localhost:8000/gmail/callback"
    gmail_token_enc_key: str | None = None
    gmail_sync_max_results: int = 15
    # Upper bound (in days) for the sync's look-back window (Plan 40). A wider window widens
    # *which* emails qualify, not *how many* are triaged — that stays capped by max_results.
    gmail_sync_max_days: int = 30
    # Max concurrent Gmail fetches + triage calls per sync (Plan 41). Running N emails
    # sequentially (a Gmail get + a Groq triage each) blows past Cloudflare's ~100s edge
    # timeout → 524; bounded concurrency keeps a full sync well under it. Kept modest to
    # respect Groq rate limits.
    gmail_sync_concurrency: int = 5
    # Chars of the email body sent to the LLM per triage (Plan 41). Full bodies (up to 20k
    # chars) are token-heavy and trip Groq's per-minute token limit → heavy throttling; the
    # gist needed to classify + draft fits in far less.
    gmail_sync_body_chars: int = 2000
    # Wall-clock budget for the triage phase of a sync (Plan 41). On expiry the endpoint
    # returns whatever finished so far instead of running past Cloudflare's ~100s edge
    # timeout (524). Keep it comfortably under 100s.
    gmail_sync_budget_seconds: float = 80.0
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

    @field_validator("frontend_url")
    @classmethod
    def _strip_trailing_slash(cls, v: str) -> str:
        # A trailing slash produces "host//accept-invite" / "host/#token=", and
        # the SPA router won't match the doubled path. Normalise it away.
        return v.rstrip("/")

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
