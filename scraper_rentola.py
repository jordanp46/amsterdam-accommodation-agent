"""
Rentola.nl scraper — furnished apartments and rooms in Amsterdam up to €1300.
Cards: div.relative.flex.gap-3... containing address + price.
Pagination: ?page=N
"""
import re
import asyncio
from datetime import date
from playwright.async_api import async_playwright

SEARCH_URL = "https://rentola.nl/huren/amsterdam?max_price=1300&furnished=1"
MAX_RENT = 1300
MAX_PAGES = 5


def _parse_id(url: str) -> str:
    # e.g. https://rentola.nl/listings/amsterdam-appartement-anne-frankstraat-pf4e257
    # ID is the trailing hex slug after the last '-p'
    m = re.search(r"-p([0-9a-f]+)$", url.rstrip("/"))
    if m:
        return f"rentola-{m.group(1)}"
    return f"rentola-{url.rstrip('/').split('/')[-1]}"


def _parse_type(text: str) -> str:
    text_l = text.lower()
    if "studio" in text_l:
        return "Studio"
    if "appartement" in text_l or "apartment" in text_l:
        return "Apartment"
    if "kamer" in text_l or "room" in text_l:
        return "Room"
    if "huis" in text_l or "house" in text_l or "woning" in text_l:
        return "House"
    return "Unknown"


def _parse_card(href: str, text: str) -> object:
    # Card text example:
    # "1-slaapkamer appartement van 38 m²\nMuiderstraat 3, 1011 PZ Amsterdam, Netherlands\n€680 / maand"
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]

    # Rent: "€680 / maand" or "€1.200 / maand"
    rent_m = re.search(r"€\s*([\d.,]+)\s*/\s*maand", text, re.I)
    if not rent_m:
        rent_m = re.search(r"€\s*([\d.,]+)", text)
    rent = None
    if rent_m:
        rent = int(rent_m.group(1).replace(".", "").replace(",", ""))

    if rent and rent > MAX_RENT:
        return None

    # Size: "38 m²" from "van 38 m²"
    size_m = re.search(r"(\d+)\s*m²", text)
    size = int(size_m.group(1)) if size_m else None

    # Street: extract from text just before "NNNN XX" postal code
    # Card text is often one line: "...van 38 m²Muiderstraat 3, 1011 PZ Amsterdam..."
    street_m = re.search(r"m²\s*([^,]+?),\s*\d{4}\s*[A-Z]{2}", text)
    if not street_m:
        # Fallback: text before first comma that contains a number (house number)
        street_m = re.search(r"([A-Za-z][^,\n]{3,40}\s+\d+[^,]*?),\s*\d{4}\s*[A-Z]{2}", text)
    street = street_m.group(1).strip() if street_m else ""

    # Neighbourhood: Amsterdam postal codes mapped to target neighbourhoods.
    # More specific sub-areas checked first so they take priority.
    pc_m = re.search(r"(\d{4})\s*[A-Z]{2}", text)
    neighbourhood = None
    if pc_m:
        pc = int(pc_m.group(1))
        if 1015 <= pc <= 1017:        # Jordaan (subset of Centrum range)
            neighbourhood = "Jordaan"
        elif 1072 <= pc <= 1075:      # De Pijp (subset of Oud-Zuid range)
            neighbourhood = "De Pijp"
        elif 1011 <= pc <= 1019:      # Centrum (broader)
            neighbourhood = "Centrum"
        elif 1052 <= pc <= 1059:      # Oud-West
            neighbourhood = "Oud-West"
        elif 1060 <= pc <= 1069:      # West (Bos en Lommer, Slotervaart)
            neighbourhood = "West"
        elif 1071 <= pc <= 1079:      # Oud-Zuid (broader)
            neighbourhood = "Oud-Zuid"
        elif 1091 <= pc <= 1099:      # Oost
            neighbourhood = "Oost"

    prop_type = _parse_type(lines[0] if lines else text)

    return {
        "source": "rentola.nl",
        "id": _parse_id(href),
        "url": href,
        "title": f"{prop_type} — {street}, Amsterdam" if street else f"{prop_type} — Amsterdam",
        "street": street,
        "city": "Amsterdam",
        "neighbourhood": neighbourhood,
        "type": prop_type,
        "rent_eur": rent,
        "rent_includes_utilities": bool(re.search(r"incl|inclusief|bills", text, re.I)),
        "size_m2": size,
        "furnished": True,  # filter enforces furnished=1
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
                    await page.wait_for_timeout(3000)
                except Exception as e:
                    print(f"  [rentola] page {page_num} load error: {e}")
                    break

                for _ in range(3):
                    await page.evaluate("window.scrollBy(0, 900)")
                    await page.wait_for_timeout(500)

                cards = await page.evaluate("""() => {
                    const links = Array.from(document.querySelectorAll('a[href*="/listings/"]'));
                    const seen = new Set();
                    return links
                        .filter(a => { if (seen.has(a.href)) return false; seen.add(a.href); return true; })
                        .map(a => {
                            const card = a.closest('div[class*="flex"][class*="gap"]') || a.parentElement;
                            return { href: a.href, text: card ? card.innerText : a.innerText };
                        });
                }""")

                if not cards:
                    print(f"  [rentola] page {page_num}: no cards found")
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

                print(f"  [rentola] page {page_num}: {new_on_page} listings")

                has_next = await page.evaluate("""() => !!document.querySelector('a[rel="next"], a[aria-label*="next"]')""")
                if not has_next or new_on_page == 0:
                    break

            await browser.close()

    except Exception as e:
        print(f"  [rentola] scraper failed: {e}")

    print(f"  [rentola] total: {len(listings)}")
    return listings


if __name__ == "__main__":
    import json
    results = asyncio.run(scrape())
    print(json.dumps(results[:3], indent=2))
