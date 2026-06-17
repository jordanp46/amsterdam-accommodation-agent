"""
HousingAnywhere.com scraper — Amsterdam listings, filtered in Python.
Loads the unfiltered search page (filters break the headless response),
then applies rent/size/city filters locally.
"""
import re
import asyncio
from datetime import date, datetime
from playwright.async_api import async_playwright

SEARCH_URL = "https://housinganywhere.com/s/Amsterdam--Netherlands"
MAX_RENT = 1300
MIN_SIZE = 8
AVAILABLE_BY = date(2026, 8, 1)   # must be available before this date


def _parse_id(url: str) -> str:
    # e.g. https://housinganywhere.com/room/ut1123703/nl/Amsterdam/vijzelstraat
    #   or https://housinganywhere.com/apartment/ut9999999/nl/Amsterdam/...
    m = re.search(r"/(?:room|apartment|studio)/(ut\d+)/", url)
    return f"ha-{m.group(1)}" if m else f"ha-{url.split('/')[-1]}"


def _parse_card(href: str, text: str) -> object:
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]

    # Title line contains "Studio in Vijzelstraat, Amsterdam"
    title_line = next((l for l in lines if " in " in l), "")
    type_street_m = re.match(r"([\w\s]+?)\s+in\s+(.+?)(?:,\s*(.+))?$", title_line)
    prop_type = type_street_m.group(1).strip() if type_street_m else "Unknown"
    street = type_street_m.group(2).strip() if type_street_m else ""
    city = type_street_m.group(3).strip() if (type_street_m and type_street_m.group(3)) else "Amsterdam"

    # Only keep Amsterdam listings
    if "amsterdam" not in city.lower() and "amsterdam" not in href.lower():
        return None

    # Rent: "€995"
    rent_m = re.search(r"€(\d[\d,]+)", text)
    rent = int(rent_m.group(1).replace(",", "")) if rent_m else None

    # Size: "8 m²"
    size_m = re.search(r"(\d+)\s*m²", text)
    size = int(size_m.group(1)) if size_m else None

    # Utilities
    incl = bool(re.search(r"incl\.", text, re.I))

    # Available from
    avail_str = None
    avail_date = None
    m = re.search(r"Available from\s+(.+)", text, re.I)
    if m:
        avail_str = m.group(1).strip()
        # Try to parse to a date for filtering
        for fmt in ("%d %B", "%d %b"):
            try:
                parsed = datetime.strptime(avail_str, fmt)
                avail_date = parsed.replace(year=2026).date()
                avail_str = avail_date.isoformat()
                break
            except ValueError:
                pass
    elif re.search(r"available now", text, re.I):
        avail_str = date.today().isoformat()
        avail_date = date.today()

    # Apply filters
    if rent and rent > MAX_RENT:
        return None
    if size and size < MIN_SIZE:
        return None
    if avail_date and avail_date > AVAILABLE_BY:
        return None

    listing_id = _parse_id(href)

    return {
        "source": "housinganywhere.com",
        "id": listing_id,
        "url": href,
        "title": f"{prop_type} — {street}, {city}",
        "street": street,
        "city": city,
        "neighbourhood": None,
        "type": prop_type,
        "rent_eur": rent,
        "rent_includes_utilities": incl,
        "size_m2": size,
        "furnished": True,  # HousingAnywhere is always furnished
        "available_from": avail_str,
        "available_until": None,
        "date_found": date.today().isoformat(),
    }


async def scrape() -> list[dict]:
    listings = []
    seen_ids: set[str] = set()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1440, "height": 900},
        )
        page = await ctx.new_page()

        await page.goto(SEARCH_URL, wait_until="load", timeout=30000)
        await page.wait_for_timeout(5000)

        # Scroll to trigger lazy loading
        for _ in range(6):
            await page.evaluate("window.scrollBy(0, 1200)")
            await page.wait_for_timeout(800)

        cards = await page.evaluate("""() => {
            const links = Array.from(document.querySelectorAll(
                'a[href*="/room/"], a[href*="/apartment/"], a[href*="/studio/"]'
            )).filter(a => /\\/ut\\d+\\//.test(a.href));
            const seen = new Set();
            return links
                .filter(a => { if (seen.has(a.href)) return false; seen.add(a.href); return true; })
                .map(a => {
                    const card = a.closest('article, li, [class*="Card"], [class*="card"]') || a.parentElement;
                    return { href: a.href, text: card ? card.innerText : a.innerText };
                });
        }""")

        print(f"  [housinganywhere] {len(cards)} cards found on page")

        for card in cards:
            listing_id = _parse_id(card["href"])
            if listing_id in seen_ids:
                continue
            seen_ids.add(listing_id)
            parsed = _parse_card(card["href"], card["text"])
            if parsed:
                listings.append(parsed)

        await browser.close()

    print(f"  [housinganywhere] total after filters: {len(listings)}")
    return listings


if __name__ == "__main__":
    import json
    results = asyncio.run(scrape())
    print(json.dumps(results[:2], indent=2))
