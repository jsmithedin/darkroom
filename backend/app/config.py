from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, read from the environment (or `.env`)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://darkroom:darkroom@localhost:5432/darkroom"
    public_base_url: str = "https://film.jamielab.uk"
    allowed_emails: list[str] = []
    session_secret: str = "change-me"
    google_client_id: str = ""
    google_client_secret: str = ""
    frontend_dist: str = "frontend/dist"
