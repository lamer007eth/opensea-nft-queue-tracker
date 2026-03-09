from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib


@dataclass(slots=True)
class AppConfig:
    collection_slug: str
    token_id: str
    check_interval_seconds: int
    output_log_file: str
    opensea_api_key: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_enabled: bool = False

    @classmethod
    def from_toml(cls, path: Path) -> "AppConfig":
        data = tomllib.loads(path.read_text(encoding="utf-8"))

        required = [
            "collection_slug",
            "token_id",
            "check_interval_seconds",
            "output_log_file",
        ]
        missing = [key for key in required if key not in data]
        if missing:
            raise ValueError(f"Missing required config keys: {', '.join(missing)}")

        cfg = cls(
            collection_slug=str(data["collection_slug"]).strip(),
            token_id=str(data["token_id"]).strip(),
            check_interval_seconds=int(data["check_interval_seconds"]),
            output_log_file=str(data["output_log_file"]).strip(),
            opensea_api_key=str(data.get("opensea_api_key", "")).strip(),
            telegram_bot_token=str(data.get("telegram_bot_token", "")).strip(),
            telegram_chat_id=str(data.get("telegram_chat_id", "")).strip(),
            telegram_enabled=_to_bool(data.get("telegram_enabled", False)),
        )

        if not cfg.collection_slug:
            raise ValueError("collection_slug cannot be empty")
        if not cfg.token_id:
            raise ValueError("token_id cannot be empty")
        if cfg.check_interval_seconds <= 0:
            raise ValueError("check_interval_seconds must be > 0")
        if not cfg.output_log_file:
            raise ValueError("output_log_file cannot be empty")

        return cfg


def _to_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off", ""}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return False
