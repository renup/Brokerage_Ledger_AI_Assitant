from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Where to find ledger-core. Can be overridden with LEDGER_CORE_URL in .env.
    ledger_core_url: str = "http://localhost:8000"
    # The assistant's own database file. Named differently from ledger-core's
    # DATABASE_URL on purpose, because both services read the same .env file
    # and would otherwise pick up each other's setting.
    assistant_database_url: str = "sqlite:///assistant.db"
    # A secret mixed into the customer-id hash (see auth.py). Change it for real use.
    customer_hash_secret: str = "dev-only-secret-change-me"

    # extra="ignore": the shared .env also holds ledger-core's settings (JWT_SECRET etc.).
    # Without this, pydantic would reject them as unknown fields.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
