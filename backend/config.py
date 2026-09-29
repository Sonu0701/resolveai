from __future__ import annotations
import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")

def _path(name: str, default: str) -> Path:
    value = Path(os.getenv(name, default))
    return value if value.is_absolute() else BASE_DIR / value

@dataclass(frozen=True)
class Settings:
    app_env: str = os.getenv("APP_ENV", "development")
    database_path: Path = _path("DATABASE_PATH", "storage/resolveai.db")
    chroma_dir: Path = _path("CHROMA_PERSIST_DIR", "chroma_db")
    mistral_model: str = os.getenv("MISTRAL_MODEL", "mistral-small-latest")
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
    mistral_api_key: str | None = os.getenv("MISTRAL_API_KEY")
    policy_collection: str = "novacart_policies"
    ticket_collection: str = "novacart_resolved_tickets"
    max_message_chars: int = 5000

    @property
    def demo_mode(self) -> bool:
        return not bool(self.mistral_api_key)

settings = Settings()
settings.database_path.parent.mkdir(parents=True, exist_ok=True)
settings.chroma_dir.mkdir(parents=True, exist_ok=True)
