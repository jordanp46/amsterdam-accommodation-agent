"""
Huurwoningen.nl scraper — apartments, houses, studios, rooms in Amsterdam up to €1300.
Cards use selector: section.listing-search-item
Pagination: ?page=N appended to the base URL.
"""
import re
import asyncio
from datetime import date
from playwright.async_api import async_playwright

SEARCH_URL = (
    "https://www.huurwoningen.nl/in/amsterdam/"
    "?huurprijs=0-1300&interieur=gemeubileerd"
)
MAX_RENT = 1300
MAX_PAGES = 5


def _parse_id(url: str) -> str:
    # e.g. https://www.huurwoningen.nl/huren/amsterdam/207d4173/akbarstraat/
    m = re.search(r"/huren/amsterdam/([0-9a-f]+)/", url)
    return f"hw-{m.group(1)}" if m else f"hw-{url.rstrip('/').split('/')[-1]}"


def _parse_type(text: str) -> str:
    text_l = text.lower()
    if "studio" in text_l:
        return "Studio"
    if "appartement" in text_l:
        return "Apartment"
    if "kamer" in text_l:
        return "Room"
    if "huis" in text_l or "woning" in text_l:
        return "House"
    return "Unknown"


def _parse_card(href: str, text: str) -> object:
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]

    # Rent: "€ 3.950 per maand" (non-breaking space after €)
    rent_m = re.search(r"€\s*([\d.,]+)\s*per\s+maand", text, re.I)
    rent = None
    if rent_m:
        rent = int(rent_m.group(1).replace(".", "").replace(",", ""))

    if rent and rent > MAX_RENT:
        return None

    # Size: "111 m²"
    size_m = re.search(r"(\d+)\s*m²", text)
    size = int(size_m.group(1)) if size_m else None

    # Furnished: "Gemeubileerd" or "Gestoffeerd"
    furnished = bool(re.search(r"gemeubileerd|gestoffeerd", text, re.I))

    # Neighbourhood: in parentheses after postal code "1061 DV Amsterdam (De Kolenkit)"
    hood_m = re.search(r"\(([^)]+)\)", text)
    neighbourhood = hood_m.group(1).strip() if hood_m else None

    # Street: second line of card, type + street e.g. "Huis Akbarstraat"
    skip = {"nieuw", "new", "bewaar als favoriet", "favoriet"}
    title_line = next(
        (l for l in lines if l.lower() not in skip and not re.match(r"^€", l)),
        "",
    )
    # Extract street (everything after property type word)
    street_m = re.match(r"(?:Huis|Appartement|Studio|Kamer|Woning)\s+(.+)", title_line, re.I)
    street = street_m.group(1).strip() if street_m else title_line

    prop_type = _parse_type(title_line or text)

    return {
        "source": "huurwoningen.nl",
        "id": _parse_id(href),
        "url": href,
        "title": f"{prop_type} — {street}, Amsterdam" if street else f"{prop_type} — Amsterdam",
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


async def scrape() -> list[dict]:
    listings = []
    seen_ids: set[str] = set()

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            ctx = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1440, "height": 900},
            )
            page = await ctx.new_page()

            for page_num in range(1, MAX_PAGES + 1):
                url = SEARCH_URL + (f"&page={page_num}" if page_num > 1 else "")
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    await page.wait_for_timeout(2500)
                except Exception as e:
                    print(f"  [huurwoningen] page {page_num} load error: {e}")
                    break

                cards = await page.evaluate("""() => {
                    const sections = Array.from(document.querySelectorAll('section.listing-search-item'));
                    return sections.map(s => {
                        const a = s.querySelector('a[href*="/huren/amsterdam/"]');
                        return a ? { href: a.href, text: s.innerText } : null;
                    }).filter(Boolean);
                }""")

                if not cards:
                    print(f"  [huurwoningen] page {page_num}: no cards found")
                    break

                new_on_page = 0
                for card in cards:
                    listing_id = _parse_id(card["href"])
                    if listing_id in seen_ids:
                        continue
                    seen_ids.add(listing_id)
                    try:
                        parsed = _parse_card(card["href"], card["text"])
                        if parsed:
                            listings.append(parsed)
                            new_on_page += 1
                    except Exception:
                        pass

                print(f"  [huurwoningen] page {page_num}: {new_on_page} listings")
                if new_on_page == 0:
                    break

            await browser.close()

    except Exception as e:
        print(f"  [huurwoningen] scraper failed: {e}")

    print(f"  [huurwoningen] total: {len(listings)}")
    return listings


if __name__ == "__main__":
    import json
    results = asyncio.run(scrape())
    print(json.dumps(results[:3], indent=2))
