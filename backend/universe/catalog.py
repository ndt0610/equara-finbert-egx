import json
from pathlib import Path

CATALOG_PATH = Path(__file__).with_name("us_universe_v1.json")


def load_universe() -> dict:
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    items = catalog["items"]
    if len(items) != 50 or len({item["ticker"] for item in items}) != len(items):
        raise ValueError("US_UNIVERSE_INVALID")
    return catalog


def universe_by_ticker() -> dict[str, dict]:
    return {row["ticker"]: row for row in load_universe()["items"]}
