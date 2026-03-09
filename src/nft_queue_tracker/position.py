from __future__ import annotations

from nft_queue_tracker.models import Listing


def normalize_token_id(token_id: str) -> str:
    token_id = str(token_id).strip()
    if token_id.isdigit():
        return str(int(token_id))
    return token_id


def deduplicate_listings_by_token_min_price(listings: list[Listing]) -> list[Listing]:
    """Keep one listing per token_id, choosing the minimum price entry."""
    by_token: dict[str, Listing] = {}

    for listing in listings:
        token_key = normalize_token_id(listing.token_id)
        existing = by_token.get(token_key)

        if existing is None or _is_better_listing(listing, existing):
            by_token[token_key] = listing

    return list(by_token.values())


def _is_better_listing(candidate: Listing, current: Listing) -> bool:
    candidate_price = float("inf") if candidate.price_native is None else candidate.price_native
    current_price = float("inf") if current.price_native is None else current.price_native

    if candidate_price < current_price:
        return True
    if candidate_price > current_price:
        return False

    candidate_listed = candidate.listed_at.timestamp() if candidate.listed_at else float("inf")
    current_listed = current.listed_at.timestamp() if current.listed_at else float("inf")
    return candidate_listed < current_listed


def sort_listings_for_queue(listings: list[Listing]) -> list[Listing]:
    # Primary sort by price ascending, then by listing timestamp.
    return sorted(
        listings,
        key=lambda x: (
            float("inf") if x.price_native is None else x.price_native,
            x.listed_at.timestamp() if x.listed_at else float("inf"),
            normalize_token_id(x.token_id),
        ),
    )


def find_listing_position(sorted_listings: list[Listing], token_id: str) -> tuple[int | None, int]:
    wanted = normalize_token_id(token_id)
    for index, listing in enumerate(sorted_listings, start=1):
        if normalize_token_id(listing.token_id) == wanted:
            return index, len(sorted_listings)
    return None, len(sorted_listings)


def find_all_listing_positions(sorted_listings: list[Listing], token_id: str) -> list[int]:
    wanted = normalize_token_id(token_id)
    return [
        index
        for index, listing in enumerate(sorted_listings, start=1)
        if normalize_token_id(listing.token_id) == wanted
    ]
