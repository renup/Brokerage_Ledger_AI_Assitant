from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Where to find ledger-core. Can be overridden with LEDGER_CORE_URL in .env.
    ledger_core_url: str = "http://localhost:8000"
    # The assistant's own Postgres database (required, no default). Named differently from
    # ledger-core's DATABASE_URL on purpose, because both services read the same .env file
    # and would otherwise pick up each other's setting.
    assistant_database_url: str
    # A secret mixed into the customer-id hash (see auth.py). Change it for real use.
    customer_hash_secret: str = "dev-only-secret-change-me"

 # --- Language model settings (step 4.2) ---
    # Where the model server listens. Ollama serves an OpenAI-style API under /v1.
    # Moving to another provider later means changing only this and the two below.
    llm_base_url: str = "http://localhost:11434/v1"
    # Ollama ignores the key, but OpenAI-style APIs always expect one, so we send a placeholder.
    llm_api_key: str = "ollama"
    # The exact model name from `ollama list`.
    llm_model: str = "qwen2.5:7b-instruct"
    # Randomness of the reply: 0 is very predictable, 1 is creative. 0.2 suits factual banking answers.
    llm_temperature: float = 0.2
    # Hard cap on how many tokens one reply may use. This is where 4.1 pays off:
    # 512 tokens is roughly 380 English words.
    llm_max_tokens: int = 512

    # The Hugging Face name of the model's tokenizer. Ollama's name ("qwen2.5:7b-instruct")
    # is not a Hugging Face repo, so we need this separately for counting tokens.
    llm_tokenizer: str = "Qwen/Qwen2.5-7B-Instruct"
    # Most history tokens we replay to the model on one turn. Older messages are left out.
    history_token_budget: int = 6000
    
    # extra="ignore": the shared .env also holds ledger-core's settings (JWT_SECRET etc.).
    # Without this, pydantic would reject them as unknown fields.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
