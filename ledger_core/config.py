from pydantic_settings import BaseSettings, SettingsConfigDict


# Settings are read from environment variables / the .env file.
# Field names match env var names case-insensitively (jwt_secret <- JWT_SECRET).
class Settings(BaseSettings):
    # Has a default, so it's optional in .env
    database_url: str = "sqlite:///ledger.db"
    # No default = required. The app refuses to start without it.
    jwt_secret: str
    # HS256 = sign tokens with one shared secret
    jwt_algorithm: str = "HS256"
    # "60" in .env is converted from text to a number automatically
    token_expire_minutes: int = 60

    # Where to find the .env file (relative to where you run the command).
    # extra="ignore": the shared .env also holds the assistant's and Postgres's settings
    # (LLM_*, *_DB_PASSWORD). Without this, pydantic would reject them as unknown fields.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


# One shared settings object that the rest of the app imports
settings = Settings()
