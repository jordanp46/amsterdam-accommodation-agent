"""
Pararius.nl scraper — furnished rooms, studios, apartments in Amsterdam up to €1300.
"""
import re
import asyncio
from datetime import date
from playwright.async_api import async_playwright

SEARCH_URLS = [
    "https://www.pararius.nl/huurwoningen/amsterdam",
]
MAX_RENT = 1300
MAX_PAGES = 5


def _parse_id(url: str) -> str:
    # e.g. https://www.pararius.nl/appartement-te-huur/amsterdam/f3571ce9/delflandlaan
    parts = url.rstrip("/").split("/")
    for i, p in enumerate(parts):
        if len(p) == 8 and all(c in "0123456789abcdef" for c in p):
            return f"pararius-{p}"
    return f"pararius-{parts[-1]}"


def _parse_type(url: str) -> str:
    if "appartement" in url:
        return "Apartment"
    if "kamer" in url:
        return "Room"
    if "studio" in url:
        return "Studio"
    if "huurwoning" in url or "woning" in url:
        return "House"
    return "Unknown"


def _parse_card(href: str, text: str) -> dict:
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]

    # Title line — skip badge words like "Uitgelicht"
    badge_words = {"uitgelicht", "nieuw", "verhuurd", "new", "featured"}
    title_line = next(
        (l for l in lines if l.lower() not in badge_words and not l.lower().startswith("bewaar")),
        ""
    )

    # Street — first word(s) before the number
    # e.g. "Appartement Cornelis Schuytstraat 10 1" → "Cornelis Schuytstraat"
    street_m = re.search(r"(?:Appartement|Kamer|Studio|Huis|Woning)\s+(.+?)(?:\s+\d)", title_line, re.I)
    street = street_m.group(1).strip() if street_m else title_line

    # Neighbourhood — in parentheses after postal code
    hood_m = re.search(r"\(([^)]+)\)", text)
    neighbourhood = hood_m.group(1).strip() if hood_m else None

    # Rent
    rent_m = re.search(r"€\s*([\d.,]+)\s*per\s*maand", text, re.I)
    rent = None
    if rent_m:
        rent = int(rent_m.group(1).replace(".", "").replace(",", ""))

    # Size
    size_m = re.search(r"(\d+)\s*m²", text)
    size = int(size_m.group(1)) if size_m else None

    # Furnished
    furnished = bool(re.search(r"gemeubileerd|gestoffeerd", text, re.I))

    prop_type = _parse_type(href)
    listing_id = _parse_id(href)

    return {
        "source": "pararius.nl",
        "id": listing_id,
        "url": href,
        "title": f"{prop_type} — {street}, Amsterdam",
        "street": street,
        "city": "Amsterdam",
        "neighbourhood": neighbourhood,
        "type": prop_type,
        "rent_eur": rent,
        "rent_includes_utilities": False,
        "size_m2": size,
        "furnished": furnished,
        "available_from": None,
        "available_until": None,
        "date_found": date.today().isoformat(),
    }


async def _scrape_url(page, base_url: str, seen_ids: set) -> list[dict]:
    listings = []
    for page_num in range(1, MAX_PAGES + 1):
        url = base_url + (f"/pagina-{page_num}" if page_num > 1 else "")
        try:
            await page.goto(url, wait_until="load", timeout=30000)
        except Exception:
            await page.goto(url, timeout=30000)
        await page.wait_for_timeout(1500)

        cards = await page.evaluate("""() => {
            const items = document.querySelectorAll('li.search-list__item--listing');
            return Array.from(items).map(li => {
                const a = li.querySelector('a[href*="-te-huur/"], a[href*="huurwoningen"]');
                return { href: a ? a.href : null, text: li.innerText };
            }).filter(c => c.href);
        }""")

        if not cards:
            break

        new_on_page = 0
        for card in cards:
            listing_id = _parse_id(card["href"])
            if listing_id in seen_ids:
                continue
            seen_ids.add(listing_id)
            parsed = _parse_card(card["href"], card["text"])
            if parsed["rent_eur"] and parsed["rent_eur"] <= MAX_RENT:
                listings.append(parsed)
                new_on_page += 1

        print(f"  [pararius] {base_url.split('/')[-1]} page {page_num}: {new_on_page} listings")

        # Check if there's a next page
        has_next = await page.evaluate("""() => {
            const next = document.querySelector('a[aria-label="Volgende pagina"], a.pagination__link--next');
            return !!next;
        }""")
        if not has_next:
            break

    return listings


async def scrape() -> list[dict]:
    listings = []
    seen_ids: set[str] = set()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36"
        )
        page = await ctx.new_page()

        for url in SEARCH_URLS:
            results = await _scrape_url(page, url, seen_ids)
            listings.extend(results)

        await browser.close()

    print(f"  [pararius] total: {len(listings)}")
    return listings


if __name__ == "__main__":
    import json
    results = asyncio.run(scrape())
    print(json.dumps(results[:2], indent=2))
