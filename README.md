# OpenSea NFT Queue Tracker

A console-based Python 3.11+ tracker for monitoring your NFT position in an OpenSea collection sale queue.

## Features

- Fetches active collection listings every `check_interval_seconds`.
- Deduplicates listings by `token_id` (keeps the minimum price per token).
- Calculates your NFT queue position from the deduplicated list.
- Prints a compact human-readable status block in the console every cycle.
- Writes a short machine-friendly line to a log file every cycle.
- Stores last known position in a local state file across restarts.
- Supports one-time validation mode (`--validate-once`) with detailed diagnostics.
- Optional Telegram notifications:
  - one startup message after the first successful check,
  - then only on position change.

## Project Structure

- `main.py` - entry point.
- `config.toml` - runtime configuration.
- `requirements.txt` - Python dependencies.
- `src/nft_queue_tracker/config.py` - config loading and validation.
- `src/nft_queue_tracker/models.py` - listing model.
- `src/nft_queue_tracker/position.py` - deduplication, sorting, and position helpers.
- `src/nft_queue_tracker/tracker.py` - main loop, output, logging, state, Telegram flow.
- `src/nft_queue_tracker/telegram_notifier.py` - Telegram Bot API sender (`sendMessage`).
- `src/nft_queue_tracker/providers/base.py` - provider interface.
- `src/nft_queue_tracker/providers/opensea_api.py` - OpenSea API implementation.

## Requirements

- Python 3.11+

## Installation

```bash
python -m venv .venv
.venv\\Scripts\\activate
pip install -r requirements.txt
```

## Configuration

Edit `config.toml`:

```toml
collection_slug = "cambriaislands"
token_id = "2485"
check_interval_seconds = 300
output_log_file = "tracker.log"
opensea_api_key = "PASTE_OPENSEA_KEY"

telegram_enabled = true
telegram_bot_token = "PASTE_TELEGRAM_BOT_TOKEN"
telegram_chat_id = "644262842"
```

Notes:
- If Telegram is disabled or not configured, tracking still works normally.
- If Telegram send fails, the tracker logs the error and continues.

## Run

Normal loop mode:

```bash
python main.py
```

One-time validation mode:

```bash
python main.py --validate-once
```

## Queue Logic

1. Fetch active listings from OpenSea.
2. Group by `token_id`.
3. Keep one listing per token with minimum `price_native`.
4. Sort queue by:
   - `price_native` ascending,
   - `listed_at` ascending,
   - normalized `token_id`.
5. Find target `token_id` position (1-based).

## Console Output

Each cycle prints a compact status block with:
- collection name (fallback: `collection_slug`),
- floor price,
- top offer,
- listed count,
- your position,
- your price,
- timestamp.

If floor or top offer is unavailable (or non-positive), it prints `N/A`.

## Telegram Notifications

Uses Telegram Bot API `sendMessage` with plain text.

Message rules:
- First successful check in current run: sends `Tracker started`.
- Later checks: sends only when position changes (`from X -> Y`).
- No message when position is unchanged.

## Files Written at Runtime

- Log file: path from `output_log_file`
  - line format: `timestamp | token_id | position | total | price_eth`
- State file: same base name as log file, suffix `.state.json`
  - stores last known position for restart continuity.

## Networking and Retries

OpenSea requests use retries with backoff for temporary errors (e.g. `429`, `5xx`, network exceptions).

## Extensibility

Provider architecture is interface-based (`ListingsProvider`), so data source can be swapped later (for example, HTML parsing) without changing queue calculation logic.
