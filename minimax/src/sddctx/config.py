"""配置：集中读取环境变量，并支持仓库根目录的 ``.env``。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parents[1]  # minimax/


def load_dotenv(path: Path) -> None:
    """读取 KEY=VALUE 形式的 .env，不覆盖已存在的环境变量。"""

    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _pick_store() -> str:
    explicit = os.environ.get("SDDCTX_STORE")
    if explicit:
        return explicit
    try:
        import pyseekdb  # noqa: F401
    except Exception:
        return "sqlite"
    return "seekdb"


@dataclass
class Settings:
    home: Path
    store_backend: str
    seekdb_path: Path
    seekdb_database: str
    seekdb_embedding: str
    sqlite_path: Path
    minimax_api_key: str
    minimax_base_url: str
    minimax_model: str
    minimax_timeout: int
    powercontext_url: str
    powercontext_token: str
    powercontext_scope_id: str
    powercontext_enabled: bool
    extra: dict = field(default_factory=dict)

    @classmethod
    def load(cls) -> Settings:
        load_dotenv(PROJECT_ROOT / ".env")
        home = Path(os.environ.get("SDDCTX_HOME", str(PROJECT_ROOT / ".sddctx"))).expanduser()
        pc_url = os.environ.get("POWERCONTEXT_URL", "http://127.0.0.1:8000").rstrip("/")
        return cls(
            home=home,
            store_backend=_pick_store(),
            seekdb_path=Path(os.environ.get("SDDCTX_SEEKDB_PATH", str(home / "seekdb"))).expanduser(),
            seekdb_database=os.environ.get("SDDCTX_SEEKDB_DATABASE", "sddctx"),
            seekdb_embedding=os.environ.get("SDDCTX_SEEKDB_EMBEDDING", "off").lower(),
            sqlite_path=Path(os.environ.get("SDDCTX_SQLITE_PATH", str(home / "sddctx.db"))).expanduser(),
            minimax_api_key=os.environ.get("MINIMAX_API_KEY", ""),
            minimax_base_url=os.environ.get("MINIMAX_BASE_URL", "https://api.minimaxi.com/v1").rstrip("/"),
            minimax_model=os.environ.get("MINIMAX_MODEL", "MiniMax-M3.1-Flash"),
            minimax_timeout=int(os.environ.get("MINIMAX_TIMEOUT", "300")),
            powercontext_url=pc_url,
            powercontext_token=os.environ.get("POWERCONTEXT_TOKEN", ""),
            powercontext_scope_id=os.environ.get("POWERCONTEXT_SCOPE_ID", ""),
            powercontext_enabled=os.environ.get("POWERCONTEXT_ENABLED", "1") not in {"0", "false", "off"},
        )

    def ensure_home(self) -> Path:
        self.home.mkdir(parents=True, exist_ok=True)
        return self.home
