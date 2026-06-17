#!/usr/bin/env python3
"""
Amsterdam housing scraper — CLI runner.

Usage:
    python3 run.py                  # scrape all sources, alert on new listings
    python3 run.py --dry-run        # show new listings without saving or alerting
    python3 run.py --stats          # show DB stats and exit
    python3 run.py --json <path>    # skip scraping, process an existing listings.json
"""
import argparse
import asyncio
import json
import sys
from datetime import date
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
    return data if isinstance(data, list) else data.get("listings", [])


async def scrape_all() -> list[dict]:
    from scraper_kamernet import scrape as scrape_kamernet
    from scraper_pararius import scrape as scrape_pararius
    from scraper_housinganywhere import scrape as scrape_ha
    from scraper_spotahome import scrape as scrape_spotahome
    from scraper_huurwoningen import scrape as scrape_huurwoningen
    from scraper_rentola import scrape as scrape_rentola
    from scraper_123wonen import scrape as scrape_123wonen

    print("Scraping Kamernet...")
    kamernet = await scrape_kamernet()

    print("Scraping Pararius...")
    pararius = await scrape_pararius()

    print("Scraping HousingAnywhere...")
    ha = await scrape_ha()

    print("Scraping Spotahome...")
    spotahome = await scrape_spotahome()

    print("Scraping Huurwoningen...")
    huurwoningen = await scrape_huurwoningen()

    print("Scraping Rentola...")
    rentola = await scrape_rentola()

    print("Scraping 123wonen...")
    w123 = await scrape_123wonen()

    all_listings = kamernet + pararius + ha + spotahome + huurwoningen + rentola + w123

    # Deduplicate by id
    seen: set[str] = set()
    unique = []
    for l in all_listings:
        if l["id"] not in seen:
            seen.add(l["id"])
            unique.append(l)

    # Write merged listings.json
    output = {
        "generated_at": date.today().isoformat(),
        "sources_scraped": [
            "kamernet.nl", "pararius.nl", "housinganywhere.com",
            "spotahome.com", "huurwoningen.nl", "rentola.nl", "123wonen.nl",
        ],
        "totals": {
            "kamernet": len(kamernet),
            "pararius": len(pararius),
            "housinganywhere": len(ha),
            "spotahome": len(spotahome),
            "huurwoningen": len(huurwoningen),
            "rentola": len(rentola),
            "123wonen": len(w123),
            "total": len(unique),
        },
        "listings": unique,
    }
    out_path = Path(LISTINGS_JSON)
    out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False))
    print(f"\nWrote {len(unique)} listings to {out_path}")
    return unique


def main():
    parser = argparse.ArgumentParser(description="Amsterdam housing scraper runner")
    parser.add_argument("--json", default=None, help="Skip scraping, use existing listings.json")
    parser.add_argument("--dry-run", action="store_true", help="Don't save to DB or send alerts")
    parser.add_argument("--stats", action="store_true", help="Show DB stats and exit")
    args = parser.parse_args()

    if args.stats:
        print(f"Listings in DB: {db.count()}")
        return

    if args.json:
        print(f"Loading listings from {args.json}...")
        listings = load_listings(args.json)
        print(f"  Found {len(listings)} listings")
    else:
        listings = asyncio.run(scrape_all())

    new = db.find_new(listings)
    print(f"\nNew listings (not yet seen): {len(new)}")

    if not new:
        print("No new listings — nothing to do.")
        return

    print("\nNew listings:")
    for l in new:
        rent = f"€{l.get('rent_eur', '?')}/mo"
        print(f"  [{l.get('source','?')}] {l.get('title','?')} — {rent} — {l.get('neighbourhood') or l.get('city','?')} — {l.get('url','')}")

    if args.dry_run:
        print("\n[dry-run] Skipping DB save and email alert.")
        return

    db.save(new)
    print(f"\nSaved {len(new)} new listing(s) to DB.")
    email_alert.send_alerts(new)


if __name__ == "__main__":
    main()
