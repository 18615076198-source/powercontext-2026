from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env")


@dataclass(frozen=True)
class Settings:
    base_dir: Path = BASE_DIR
    seekdb_host: str = os.getenv("SEEKDB_HOST", "127.0.0.1")
    seekdb_port: int = int(os.getenv("SEEKDB_PORT", "2881"))
    seekdb_user: str = os.getenv("SEEKDB_USER", "root")
    seekdb_password: str = os.getenv("SEEKDB_PASSWORD", "")
    seekdb_db: str = os.getenv("SEEKDB_DB", "labmemory")
    pc_base_url: str = os.getenv("PC_BASE_URL", "http://127.0.0.1:18080")
    pc_scope_id: str = os.getenv("PC_SCOPE_ID", "")
    pc_scope_title: str = os.getenv("PC_SCOPE_TITLE", "LabMemory RAG 课题组")
    embed_model: str = os.getenv(
        "EMBED_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    )
    embed_dim: int = 384
    app_host: str = os.getenv("APP_HOST", "0.0.0.0")
    app_port: int = int(os.getenv("APP_PORT", "8000"))

    @property
    def papers_dir(self) -> Path:
        return self.base_dir / "data" / "papers"

    @property
    def notes_dir(self) -> Path:
        return self.base_dir / "data" / "notes"

    @property
    def cache_dir(self) -> Path:
        return self.base_dir / "data" / "cache"

    @property
    def frontend_dir(self) -> Path:
        return self.base_dir / "frontend"


settings = Settings()
