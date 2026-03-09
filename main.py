from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from nft_queue_tracker.config import AppConfig
from nft_queue_tracker.providers.opensea_api import OpenSeaApiProvider
from nft_queue_tracker.tracker import NFTQueueTracker


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="OpenSea NFT queue tracker")
    parser.add_argument(
        "--validate-once",
        action="store_true",
        help="Run one-time diagnostic validation and exit.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    config_path = PROJECT_ROOT / "config.toml"
    config = AppConfig.from_toml(config_path)

    provider = OpenSeaApiProvider(api_key=config.opensea_api_key)
    tracker = NFTQueueTracker(config=config, provider=provider)

    if args.validate_once:
        tracker.run_validation_once()
        return

    tracker.run_forever()


if __name__ == "__main__":
    main()
