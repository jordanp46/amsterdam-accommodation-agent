#!/usr/bin/env python3
"""
Amsterdam housing scraper — Phase 3 CLI runner.

Usage:
    python3 run.py                  # process current listings.json
    python3 run.py --json <path>    # use a different listings.json
    python3 run.py --dry-run        # show new listings without saving or alerting
    python3 run.py --stats          # show DB stats and exit
"""
import argparse
import json
import sys
from pathlib import Path

import db
import email_alert

try:
    from config import LISTINGS_JSON
except ImportError:
    LISTINGS_JSON = "/Users/jordanproudfoot/listings.json"


def load_listings(path: str) -> list[dict]:
    p = Path(path)
    if not p.exists():
        print(f"ERROR: listings.json not found at {path}")
        sys.exit(1)
    data = json.loads(p.read_text())
    # Support both top-level list and {"listings": [...]} formats
    if isinstance(data, list):
        return data
    return data.get("listings", [])


def main():
    parser = argparse.ArgumentParser(description="Amsterdam housing scraper runner")
    parser.add_argument("--json", default=LISTINGS_JSON, help="Path to listings.json")
    parser.add_argument("--dry-run", action="store_true", help="Don't save to DB or send alerts")
    parser.add_argument("--stats", action="store_true", help="Show DB stats and exit")
    args = parser.parse_args()

    if args.stats:
        total = db.count()
        print(f"Listings in DB: {total}")
        return

    print(f"Loading listings from {args.json}...")
    listings = load_listings(args.json)
    print(f"  Found {len(listings)} listings in file")

    new = db.find_new(listings)
    print(f"  New listings (not in DB): {len(new)}")

    if not new:
        print("No new listings — nothing to do.")
        return

    print("\nNew listings:")
    for l in new:
        rent = f"€{l.get('rent_eur', '?')}/mo"
        print(f"  [{l.get('source','?')}] {l.get('title','?')} — {rent} — {l.get('neighbourhood','?')} — {l.get('url','')}")

    if args.dry_run:
        print("\n[dry-run] Skipping DB save and Telegram alerts.")
        return

    db.save(new)
    print(f"\nSaved {len(new)} new listing(s) to DB.")

    email_alert.send_alerts(new)


if __name__ == "__main__":
    main()
