from __future__ import annotations

from abc import ABC, abstractmethod

from nft_queue_tracker.models import Listing


class ProviderError(RuntimeError):
    """Raised when listing provider cannot fetch or parse data."""


class ListingsProvider(ABC):
    @abstractmethod
    def fetch_active_listings(self, collection_slug: str) -> list[Listing]:
        """Return active collection listings."""
