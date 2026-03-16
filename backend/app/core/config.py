from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/redline"
    anthropic_api_key: str = ""

    model_config = {"env_file": ".env"}


settings = Settings()
