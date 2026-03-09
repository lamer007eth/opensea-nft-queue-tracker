from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import logging
from pathlib import Path
import time

from nft_queue_tracker.config import AppConfig
from nft_queue_tracker.models import Listing
from nft_queue_tracker.position import (
    deduplicate_listings_by_token_min_price,
    find_all_listing_positions,
    find_listing_position,
    normalize_token_id,
    sort_listings_for_queue,
)
from nft_queue_tracker.providers.base import ListingsProvider, ProviderError
from nft_queue_tracker.telegram_notifier import TelegramNotifier


def create_logger() -> logging.Logger:
    logger = logging.getLogger("nft_queue_tracker")
    logger.setLevel(logging.INFO)

    if logger.handlers:
        return logger

    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    logger.addHandler(console_handler)
    return logger


@dataclass
class NFTQueueTracker:
    config: AppConfig
    provider: ListingsProvider

    def run_forever(self) -> None:
        logger = create_logger()
        previous_position = self._load_last_position_from_state(logger)
        notifier = TelegramNotifier(
            bot_token=self.config.telegram_bot_token,
            chat_id=self.config.telegram_chat_id,
            enabled=self.config.telegram_enabled,
        )

        telegram_started_sent = False
        telegram_previous_position: int | None = None

        logger.info(
            "Started tracking: collection_slug=%s, token_id=%s, interval=%ss",
            self.config.collection_slug,
            self.config.token_id,
            self.config.check_interval_seconds,
        )

        if previous_position is not None:
            logger.info("Loaded last known position from state: %s", previous_position)

        while True:
            now = datetime.now().isoformat(timespec="seconds")
            try:
                listings = self.provider.fetch_active_listings(self.config.collection_slug)
                deduplicated = deduplicate_listings_by_token_min_price(listings)
                sorted_listings = sort_listings_for_queue(deduplicated)
                position, total = find_listing_position(sorted_listings, self.config.token_id)

                snapshot = self._safe_fetch_collection_snapshot(logger)
                collection_name = self._resolve_collection_name(snapshot)

                floor_price_eth = self._extract_floor_price_eth(snapshot, sorted_listings)
                top_offer_eth = self._extract_top_offer_eth(snapshot)

                my_price_eth: float | None = None
                if position is not None:
                    listing = sorted_listings[position - 1]
                    my_price_eth = self._wei_to_eth(listing.price_native)

                self._print_status_block(
                    now=now,
                    collection_name=collection_name,
                    floor_price_eth=floor_price_eth,
                    top_offer_eth=top_offer_eth,
                    listed=total,
                    position=position,
                    my_price_eth=my_price_eth,
                )

                self._append_status_log(
                    timestamp=now,
                    token_id=self.config.token_id,
                    position=position,
                    total=total,
                    price_eth=my_price_eth,
                    logger=logger,
                )

                self._handle_telegram_notifications(
                    notifier=notifier,
                    logger=logger,
                    collection_name=collection_name,
                    floor_price_eth=floor_price_eth,
                    top_offer_eth=top_offer_eth,
                    listed=total,
                    position=position,
                    started_sent=telegram_started_sent,
                    previous_position=telegram_previous_position,
                )

                if not telegram_started_sent:
                    telegram_started_sent = True
                    telegram_previous_position = position
                else:
                    telegram_previous_position = position

                if position is not None:
                    if previous_position is not None and position != previous_position:
                        direction = "up" if position < previous_position else "down"
                        print(
                            f"Position changed: {previous_position} -> {position} ({direction})"
                        )
                        print()
                    previous_position = position
                    self._save_last_position_to_state(position, logger)

            except ProviderError as exc:
                logger.error("[%s] Data provider error: %s", now, exc)
                print()
            except Exception as exc:
                logger.exception("[%s] Unexpected error: %s", now, exc)
                print()

            time.sleep(self.config.check_interval_seconds)

    def run_validation_once(self) -> None:
        print("=== OpenSea Validation Mode (one-time) ===")
        print(f"collection_slug: {self.config.collection_slug}")
        print(f"token_id: {self.config.token_id}")

        listings = self.provider.fetch_active_listings(self.config.collection_slug)
        deduplicated = deduplicate_listings_by_token_min_price(listings)
        stats = getattr(self.provider, "last_fetch_stats", None)
        snapshot = self._safe_fetch_collection_snapshot(None)

        total_raw = stats.total_raw_records if stats is not None else len(listings)
        token_ok = stats.token_id_extracted if stats is not None else len(listings)
        price_ok = stats.price_extracted if stats is not None else sum(1 for x in listings if x.price_native is not None)
        listed_at_ok = stats.listed_at_extracted if stats is not None else sum(1 for x in listings if x.listed_at is not None)
        dropped = stats.dropped_without_token_id if stats is not None else 0
        unique_token_count = len(deduplicated)
        collapsed_duplicates = max(0, len(listings) - unique_token_count)

        print("\n--- Extraction stats ---")
        print(f"Total raw records: {total_raw}")
        print(f"Records with token_id extracted: {token_ok}")
        print(f"Records with price extracted: {price_ok}")
        print(f"Records with listed_at extracted: {listed_at_ok}")
        print(f"Dropped records (no token_id): {dropped}")

        print("\n--- Deduplication stats ---")
        print(f"Raw records received: {total_raw}")
        print(f"Unique token_id after dedup: {unique_token_count}")
        print(f"Collapsed duplicate records: {collapsed_duplicates}")

        floor_price_eth = self._extract_floor_price_eth(snapshot, deduplicated)
        top_offer_eth = self._extract_top_offer_eth(snapshot)
        print("\n--- Collection metrics ---")
        print(f"Collection: {self._resolve_collection_name(snapshot)}")
        print(f"Floor price: {self._format_eth_user(floor_price_eth)}")
        print(f"Top offer: {self._format_eth_user(top_offer_eth)}")

        sorted_listings = sort_listings_for_queue(deduplicated)
        first_position, total = find_listing_position(sorted_listings, self.config.token_id)
        all_positions = find_all_listing_positions(sorted_listings, self.config.token_id)

        if first_position is None:
            print("\n--- NFT not found ---")
            print(f"Target token_id found: {'yes' if all_positions else 'no'}")
            print(f"Total records received: {total_raw}")
            print(f"Records dropped: {dropped}")
            print(f"Records included in queue after dedup: {total}")
            return

        print("\n--- Position result ---")
        print(f"First position for token_id={self.config.token_id}: {first_position}/{total}")
        print(f"All positions for this token_id: {all_positions}")

        print("\n--- First 20 positions from queue start ---")
        top_end = min(total, 20)
        self._print_table(sorted_listings, 0, top_end, self.config.token_id)

        print("\n--- Window around first match (10 before + target + 10 after) ---")
        target_index = first_position - 1
        start_idx = max(0, target_index - 10)
        end_idx = min(total, target_index + 11)
        self._print_table(sorted_listings, start_idx, end_idx, self.config.token_id)

    def _state_file_path(self) -> Path:
        return Path(self.config.output_log_file).with_suffix(".state.json")

    def _load_last_position_from_state(self, logger: logging.Logger) -> int | None:
        state_path = self._state_file_path()
        try:
            payload = json.loads(state_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except Exception as exc:
            logger.warning("Failed to read state file %s: %s", state_path, exc)
            return None

        if not isinstance(payload, dict):
            return None

        if payload.get("collection_slug") != self.config.collection_slug:
            return None
        if str(payload.get("token_id", "")) != self.config.token_id:
            return None

        value = payload.get("position")
        return value if isinstance(value, int) else None

    def _save_last_position_to_state(self, position: int, logger: logging.Logger) -> None:
        state_path = self._state_file_path()
        payload = {
            "collection_slug": self.config.collection_slug,
            "token_id": self.config.token_id,
            "position": position,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        try:
            state_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning("Failed to write state file %s: %s", state_path, exc)

    def _append_status_log(
        self,
        timestamp: str,
        token_id: str,
        position: int | None,
        total: int,
        price_eth: float | None,
        logger: logging.Logger,
    ) -> None:
        position_text = str(position) if position is not None else "-"
        price_text = self._format_price_eth_log(price_eth)
        line = f"{timestamp} | {token_id} | {position_text} | {total} | {price_text}\n"
        try:
            with Path(self.config.output_log_file).open("a", encoding="utf-8") as file:
                file.write(line)
        except Exception as exc:
            logger.warning("Failed to append log file %s: %s", self.config.output_log_file, exc)

    def _handle_telegram_notifications(
        self,
        notifier: TelegramNotifier,
        logger: logging.Logger,
        collection_name: str,
        floor_price_eth: float | None,
        top_offer_eth: float | None,
        listed: int,
        position: int | None,
        started_sent: bool,
        previous_position: int | None,
    ) -> None:
        if not notifier.is_configured:
            return

        if not started_sent:
            text = self._build_telegram_message(
                title="\U0001F680 Tracker started",
                collection_name=collection_name,
                floor_price_eth=floor_price_eth,
                top_offer_eth=top_offer_eth,
                listed=listed,
                position=position,
                position_change=None,
            )
            if not notifier.send_text(text):
                logger.warning("Failed to send Telegram startup message: %s", notifier.last_error)
            return

        if position != previous_position:
            from_value = "N/A" if previous_position is None else str(previous_position)
            to_value = "N/A" if position is None else str(position)
            text = self._build_telegram_message(
                title="\U0001F504 Position changed",
                collection_name=collection_name,
                floor_price_eth=floor_price_eth,
                top_offer_eth=top_offer_eth,
                listed=listed,
                position=position,
                position_change=f"from {from_value} \u2192 {to_value}",
            )
            if not notifier.send_text(text):
                logger.warning("Failed to send Telegram position change message: %s", notifier.last_error)

    def _build_telegram_message(
        self,
        title: str,
        collection_name: str,
        floor_price_eth: float | None,
        top_offer_eth: float | None,
        listed: int,
        position: int | None,
        position_change: str | None,
    ) -> str:
        my_position_text = "N/A" if position is None else str(position)

        lines = [
            title,
            "",
            f"\U0001F334 {collection_name}",
            "",
            f"\U0001F48E Floor price: {self._format_eth_user(floor_price_eth)}",
            f"\U0001F525 Top offer: {self._format_eth_user(top_offer_eth)}",
            f"\U0001F4CC Listed: {listed}",
            f"\U0001F3AF My position: {my_position_text}",
        ]

        if position_change:
            lines.append("")
            lines.append(position_change)

        return "\n".join(lines)

    def _safe_fetch_collection_snapshot(self, logger: logging.Logger | None) -> object | None:
        fetcher = getattr(self.provider, "fetch_collection_snapshot", None)
        if not callable(fetcher):
            return None
        try:
            return fetcher(self.config.collection_slug)
        except Exception as exc:
            if logger is not None:
                logger.warning("Failed to fetch collection metrics: %s", exc)
            return None

    def _resolve_collection_name(self, snapshot: object | None) -> str:
        if snapshot is not None and isinstance(getattr(snapshot, "collection_name", None), str):
            value = snapshot.collection_name.strip()
            if value:
                return value
        return self.config.collection_slug

    def _extract_floor_price_eth(self, snapshot: object | None, sorted_listings: list[Listing]) -> float | None:
        if snapshot is not None:
            floor_native = getattr(snapshot, "floor_price_native", None)
            if isinstance(floor_native, (int, float)):
                return float(floor_native)

        for listing in sorted_listings:
            if listing.price_native is not None:
                return self._wei_to_eth(listing.price_native)
        return None

    def _extract_top_offer_eth(self, snapshot: object | None) -> float | None:
        if snapshot is None:
            return None
        value = getattr(snapshot, "top_offer_native", None)
        if not isinstance(value, (int, float)):
            return None

        if float(value) <= 0:
            return None

        converted = self._wei_to_eth(float(value))
        if converted is None or converted <= 0:
            return None

        return converted

    def _wei_to_eth(self, value: float | None) -> float | None:
        if value is None:
            return None
        return value / 1_000_000_000_000_000_000

    def _format_eth_user(self, value: float | None) -> str:
        if value is None:
            return "N/A"
        return f"{value:.4f} ETH"

    def _format_price_eth_log(self, value: float | None) -> str:
        if value is None:
            return "-"
        return f"{value:.8f}"

    def _print_status_block(
        self,
        now: str,
        collection_name: str,
        floor_price_eth: float | None,
        top_offer_eth: float | None,
        listed: int,
        position: int | None,
        my_price_eth: float | None,
    ) -> None:
        my_position_text = str(position) if position is not None else "N/A"
        my_price_text = self._format_eth_user(my_price_eth)

        print(f"\U0001F334 {collection_name}")
        print()
        print(f"\U0001F48E Floor price: {self._format_eth_user(floor_price_eth)}")
        print(f"\U0001F525 Top offer: {self._format_eth_user(top_offer_eth)}")
        print(f"\U0001F4CC Listed: {listed}")
        print()
        print(f"\U0001F3AF My position: {my_position_text}")
        print(f"\U0001F4B0 My price: {my_price_text}")
        print(f"\U0001F552 Checked at: {now}")
        print()

    def _print_table(
        self,
        sorted_listings: list[Listing],
        start_idx: int,
        end_idx: int,
        target_token_id: str,
    ) -> None:
        print("position | token_id | price_native | listed_at")
        print("-" * 78)
        wanted = normalize_token_id(target_token_id)
        for pos in range(start_idx + 1, end_idx + 1):
            listing = sorted_listings[pos - 1]
            marker = " <= target" if normalize_token_id(listing.token_id) == wanted else ""
            print(self._format_row(pos, listing) + marker)

    def _format_row(self, position: int, listing: Listing) -> str:
        listed_at_value = listing.listed_at.isoformat() if listing.listed_at else "-"
        price_value = f"{listing.price_native:.10g}" if listing.price_native is not None else "-"
        return (
            f"{position:>8} | "
            f"{listing.token_id:<12} | "
            f"{price_value:<12} | "
            f"{listed_at_value}"
        )
