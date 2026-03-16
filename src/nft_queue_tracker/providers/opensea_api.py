from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import os
import time
from typing import Any

import requests

from nft_queue_tracker.models import Listing
from nft_queue_tracker.providers.base import ListingsProvider, ProviderError


@dataclass(slots=True)
class FetchStats:
    total_raw_records: int = 0
    token_id_extracted: int = 0
    price_extracted: int = 0
    listed_at_extracted: int = 0
    dropped_without_token_id: int = 0


@dataclass(slots=True)
class CollectionSnapshot:
    collection_name: str | None = None
    floor_price_native: float | None = None
    top_offer_native: float | None = None


class OpenSeaApiProvider(ListingsProvider):
    """Fetches active listings via OpenSea REST API.

    The API schema may evolve, so parser is intentionally defensive.
    """

    BASE_URL = "https://api.opensea.io/api/v2/listings/collection/{collection_slug}/all"
    COLLECTION_URL = "https://api.opensea.io/api/v2/collections/{collection_slug}"
    COLLECTION_STATS_URL = "https://api.opensea.io/api/v2/collections/{collection_slug}/stats"
    COLLECTION_OFFERS_URL = "https://api.opensea.io/api/v2/offers/collection/{collection_slug}"

    def __init__(
        self,
        api_key: str = "",
        timeout_seconds: int = 20,
        max_retries: int = 3,
        retry_backoff_seconds: float = 2.0,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds
        self.session = requests.Session()
        self.last_fetch_stats = FetchStats()

        effective_api_key = api_key or os.getenv("OPENSEA_API_KEY", "")
        if effective_api_key:
            self.session.headers.update({"X-API-KEY": effective_api_key})

    def fetch_active_listings(self, collection_slug: str) -> list[Listing]:
        listings: list[Listing] = []
        next_cursor: str | None = None
        stats = FetchStats()

        while True:
            params: dict[str, Any] = {"limit": 50}
            if next_cursor:
                params["next"] = next_cursor

            payload = self._request_json(
                self.BASE_URL.format(collection_slug=collection_slug),
                params=params,
            )

            page_listings, page_stats = self._extract_listings(payload)
            listings.extend(page_listings)
            self._merge_stats(stats, page_stats)

            next_cursor = payload.get("next") or payload.get("next_cursor")
            if not next_cursor:
                break

        self.last_fetch_stats = stats
        return listings

    def fetch_collection_snapshot(self, collection_slug: str) -> CollectionSnapshot:
        name = self._fetch_collection_name(collection_slug)
        floor_native = self._fetch_floor_price_native(collection_slug)
        top_offer_native = self._fetch_top_offer_native(collection_slug)
        return CollectionSnapshot(
            collection_name=name,
            floor_price_native=floor_native,
            top_offer_native=top_offer_native,
        )

    def _fetch_collection_name(self, collection_slug: str) -> str | None:
        try:
            payload = self._request_json(
                self.COLLECTION_URL.format(collection_slug=collection_slug),
                params={},
            )
        except ProviderError:
            return None

        if isinstance(payload.get("name"), str) and payload["name"].strip():
            return payload["name"].strip()

        collection = payload.get("collection")
        if isinstance(collection, dict) and isinstance(collection.get("name"), str):
            value = collection["name"].strip()
            if value:
                return value

        return None

    def _fetch_floor_price_native(self, collection_slug: str) -> float | None:
        try:
            payload = self._request_json(
                self.COLLECTION_STATS_URL.format(collection_slug=collection_slug),
                params={},
            )
        except ProviderError:
            return None

        stats = payload.get("stats") if isinstance(payload.get("stats"), dict) else payload
        if not isinstance(stats, dict):
            return None

        for key in ("floor_price", "floor", "floorPrice"):
            if key not in stats:
                continue
            try:
                return float(stats[key])
            except (TypeError, ValueError):
                continue

        return None

    def _fetch_top_offer_native(self, collection_slug: str) -> float | None:
        try:
            payload = self._request_json(
                self.COLLECTION_OFFERS_URL.format(collection_slug=collection_slug),
                params={"limit": 50},
            )
        except ProviderError:
            return None

        raw_offers: list[dict[str, Any]] = []
        if isinstance(payload.get("offers"), list):
            raw_offers = [x for x in payload["offers"] if isinstance(x, dict)]
        elif isinstance(payload.get("orders"), list):
            raw_offers = [x for x in payload["orders"] if isinstance(x, dict)]

        for item in raw_offers:
            price = self._extract_offer_price_native(item)
            if price is not None and price > 0:
                return price

        return None

    def _extract_offer_price_native(self, item: dict[str, Any]) -> float | None:
        quantity = self._extract_offer_quantity(item)
        divisor = quantity if quantity and quantity > 0 else 1.0

        price_obj = item.get("price") if isinstance(item.get("price"), dict) else None
        if isinstance(price_obj, dict):
            # In collection offers, "price.value" is the total bid amount for the offer.
            # OpenSea UI shows the per-item offer, so normalize by offer quantity.
            value = price_obj.get("value")
            if value is not None:
                try:
                    parsed = float(value) / divisor
                    if parsed > 0:
                        return parsed
                except (TypeError, ValueError):
                    pass

        current = price_obj.get("current") if isinstance(price_obj, dict) else None
        if isinstance(current, dict):
            for key in ("value", "price", "decimal"):
                if key in current:
                    try:
                        parsed = float(current[key]) / divisor
                        if parsed > 0:
                            return parsed
                    except (TypeError, ValueError):
                        pass

        for key in ("current_price", "start_amount", "price"):
            value = item.get(key)
            if value is None:
                continue
            try:
                parsed = float(value) / divisor
                if parsed > 0:
                    return parsed
            except (TypeError, ValueError):
                continue

        protocol_data = item.get("protocol_data")
        if isinstance(protocol_data, dict):
            parameters = protocol_data.get("parameters")
            if isinstance(parameters, dict):
                consideration = parameters.get("consideration")
                if isinstance(consideration, list) and consideration:
                    first = consideration[0]
                    if isinstance(first, dict):
                        for key in ("startAmount", "endAmount"):
                            if key in first:
                                try:
                                    parsed = float(first[key]) / divisor
                                    if parsed > 0:
                                        return parsed
                                except (TypeError, ValueError):
                                    continue

        return None

    def _extract_offer_quantity(self, item: dict[str, Any]) -> float | None:
        value = item.get("remaining_quantity")
        if value is None:
            return None
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    def _request_json(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.session.get(url, params=params, timeout=self.timeout_seconds)

                if response.status_code in {429, 500, 502, 503, 504}:
                    raise ProviderError(
                        f"Retryable OpenSea status code: {response.status_code}"
                    )

                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ProviderError("Unexpected API response format")
                return payload
            except (requests.RequestException, ValueError, ProviderError) as exc:
                last_error = exc
                if attempt == self.max_retries:
                    break
                sleep_seconds = self.retry_backoff_seconds * (2 ** (attempt - 1))
                time.sleep(sleep_seconds)

        raise ProviderError(f"Failed to fetch listings after retries: {last_error}")

    def _extract_listings(self, payload: dict[str, Any]) -> tuple[list[Listing], FetchStats]:
        raw_listings: list[dict[str, Any]] = []
        stats = FetchStats()

        if isinstance(payload.get("listings"), list):
            raw_listings = [item for item in payload["listings"] if isinstance(item, dict)]
        elif isinstance(payload.get("orders"), list):
            raw_listings = [item for item in payload["orders"] if isinstance(item, dict)]

        stats.total_raw_records = len(raw_listings)

        result: list[Listing] = []
        for item in raw_listings:
            token_id = self._extract_token_id(item)
            price_native = self._extract_price(item)
            listed_at = self._extract_listed_at(item)

            if token_id is not None:
                stats.token_id_extracted += 1
            else:
                stats.dropped_without_token_id += 1

            if price_native is not None:
                stats.price_extracted += 1

            if listed_at is not None:
                stats.listed_at_extracted += 1

            if token_id is None:
                continue

            result.append(
                Listing(
                    token_id=token_id,
                    price_native=price_native,
                    listed_at=listed_at,
                    raw=item,
                )
            )

        return result, stats

    def _merge_stats(self, target: FetchStats, delta: FetchStats) -> None:
        target.total_raw_records += delta.total_raw_records
        target.token_id_extracted += delta.token_id_extracted
        target.price_extracted += delta.price_extracted
        target.listed_at_extracted += delta.listed_at_extracted
        target.dropped_without_token_id += delta.dropped_without_token_id

    def _extract_token_id(self, item: dict[str, Any]) -> str | None:
        candidates = [
            item.get("token_id"),
            item.get("tokenId"),
            item.get("identifier"),
            item.get("protocol_data", {})
            .get("parameters", {})
            .get("offer", [{}])[0]
            .get("identifierOrCriteria"),
            item.get("asset", {}).get("token_id"),
        ]

        for candidate in candidates:
            if candidate is None:
                continue
            value = str(candidate).strip()
            if value:
                return value
        return None

    def _extract_price(self, item: dict[str, Any]) -> float | None:
        """Best-effort price extraction in native unit (usually wei)."""
        current = item.get("price", {}).get("current") if isinstance(item.get("price"), dict) else None
        if isinstance(current, dict):
            for key in ("value", "price", "decimal"):
                if key in current:
                    try:
                        return float(current[key])
                    except (TypeError, ValueError):
                        pass

        for key in ("current_price", "start_amount", "price"):
            value = item.get(key)
            if value is None:
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                continue

        return None

    def _extract_listed_at(self, item: dict[str, Any]) -> datetime | None:
        for key in ("created_date", "listed_date", "created_at"):
            value = item.get(key)
            if not value or not isinstance(value, str):
                continue
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                continue
        return None
