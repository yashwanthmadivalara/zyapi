from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    database_path: str = "./data/viralflow.db"
    upload_dir: str = "./data/uploads"
    max_upload_bytes: int = 1_073_741_824
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5:3b"
    whisper_model: str = "base"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    youtube_client_id: str = ""
    youtube_client_secret: str = ""
    youtube_redirect_uri: str = "http://localhost:8000/api/integrations/youtube/callback"
    youtube_token_path: str = "./data/youtube-token.json"
    clip_dir: str = "./data/clips"
    clip_crf: int = 23
    clip_preset: str = "veryfast"
    default_timezone: str = "Asia/Kolkata"
    api_access_token: str = ""
    max_concurrent_jobs: int = 1
    cors_origins: str = "http://localhost:3000"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    def ensure_dirs(self) -> None:
        Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        Path(self.upload_dir).mkdir(parents=True, exist_ok=True)
        Path(self.clip_dir).mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_dirs()
