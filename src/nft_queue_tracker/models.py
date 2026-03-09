from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class Listing:
    token_id: str
    price_native: float | None = None
    listed_at: datetime | None = None
    raw: dict[str, Any] = field(default_factory=dict)
