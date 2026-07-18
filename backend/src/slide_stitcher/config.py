from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_storage_dir() -> Path:
    """User-visible default. ~/Documents/SlideVision on Mac, %USERPROFILE%\\Documents\\SlideVision on Windows."""
    home = Path.home()
    docs = home / "Documents"
    if not docs.exists():
        docs = home
    return docs / "SlideVision"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    storage_dir: Path = _default_storage_dir()
    thumb_max_dim: int = 1024
    hf_token: str = ""

    @property
    def cases_dir(self) -> Path:
        return self.storage_dir / "cases"


settings = Settings()
