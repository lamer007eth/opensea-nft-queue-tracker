from __future__ import annotations

from dataclasses import dataclass, field

import requests


@dataclass(slots=True)
class TelegramNotifier:
    bot_token: str
    chat_id: str
    enabled: bool
    timeout_seconds: int = 15
    _session: requests.Session = field(init=False, repr=False)
    last_error: str = field(init=False, default="")

    def __post_init__(self) -> None:
        self._session = requests.Session()

    @property
    def is_configured(self) -> bool:
        return bool(self.enabled and self.bot_token and self.chat_id)

    def send_text(self, text: str) -> bool:
        self.last_error = ""

        if not self.is_configured:
            self.last_error = "Telegram is disabled or not configured"
            return False

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }

        try:
            response = self._session.post(url, json=payload, timeout=self.timeout_seconds)
            response.raise_for_status()
            body = response.json()
            ok = isinstance(body, dict) and bool(body.get("ok"))
            if not ok:
                self.last_error = f"Telegram API returned not ok: {body}"
            return ok
        except Exception as exc:
            self.last_error = str(exc)
            return False
