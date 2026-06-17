"""
123wonen.nl scraper — furnished apartments, houses, studios in Amsterdam up to €1300.
Listing cards use onclick="location.href=..." so we extract URLs from that attribute.
Pagination: /huurwoningen/in/amsterdam/page/N
"""
import re
import asyncio
from datetime import date
from playwright.async_api import async_playwright

SEARCH_URL = "https://www.123wonen.nl/huurwoningen/in/amsterdam?maxhuur=1300&gemeubileerd=1"
MAX_RENT = 1300
MAX_PAGES = 5

# Dutch month names for availability parsing
NL_MONTHS = {
    "januari": "01", "februari": "02", "maart": "03", "april": "04",
    "mei": "05", "juni": "06", "juli": "07", "augustus": "08",
    "september": "09", "oktober": "10", "november": "11", "december": "12",
}

TARGET_NEIGHBOURHOODS = {
    "jordaan", "oud-zuid", "de pijp", "oud-west", "oost", "west",
    "westerpark", "bos en lommer", "de baarsjes",
}


def _parse_id(url: str) -> str:
    # e.g. https://www.123wonen.nl/huur/amsterdam/appartement/ecuplein-3587-14
    # ID = last two hyphen-separated numbers in slug
    slug = url.rstrip("/").split("/")[-1]
    m = re.search(r"-(\d+-\d+)$", slug)
    return f"123wonen-{m.group(1)}" if m else f"123wonen-{slug}"


def _parse_type(text: str) -> str:
    # "TypeBovenwoning", "TypeAppartement", "TypeStudio", "TypeKamer"
    m = re.search(r"Type\s*(Appartement|Bovenwoning|Penthouse|Woning|Huis|Studio|Kamer|Flat)", text, re.I)
    if not m:
        return "Unknown"
    t = m.group(1).lower()
    if t in ("appartement", "bovenwoning", "penthouse", "flat", "woning"):
        return "Apartment"
    if t in ("huis",):
        return "House"
    if t == "studio":
        return "Studio"
    if t == "kamer":
        return "Room"
    return "Unknown"


def _parse_available(text: str) -> object:
    # "BeschikbaarheidPer direct" → today
    if re.search(r"per direct", text, re.I):
        return date.today().isoformat()
    # "Beschikbaarheid15 juli 2026" or "Beschikbaarheid1 augustus 2026"
    m = re.search(r"Beschikbaarheid\s*(\d{1,2})\s+(\w+)\s+(\d{4})", text, re.I)
    if m:
        d, mo_name, yr = m.group(1), m.group(2).lower(), m.group(3)
        mo = NL_MONTHS.get(mo_name)
        if mo:
            return f"{yr}-{mo}-{int(d):02d}"
    return None


def _parse_card(href: str, text: str) -> object:
    # Rent: "€ 3.150,-p/mnd" — dots are thousands separators in Dutch
    rent_m = re.search(r"€\s*([\d.]+),-\s*p/mnd", text, re.I)
    if not rent_m:
        rent_m = re.search(r"€\s*([\d.]+)", text)
    rent = None
    if rent_m:
        rent = int(rent_m.group(1).replace(".", ""))

    if rent and rent > MAX_RENT:
        return None

    # Size: "Woonoppervlakte80 m²" or "80 m²"
    size_m = re.search(r"(\d+)\s*m²", text)
    size = int(size_m.group(1)) if size_m else None

    # Street: "Amsterdam, Alexanderkade" — text after last comma before newline
    street_m = re.search(r"Amsterdam,\s*(.+?)(?:\n|$)", text)
    street = street_m.group(1).strip() if street_m else ""

    # Neighbourhood: check street/text against known neighbourhood names
    text_l = (text + " " + href).lower()
    neighbourhood = None
    for hood in sorted(TARGET_NEIGHBOURHOODS, key=len, reverse=True):
        if hood in text_l:
            neighbourhood = hood.title()
            break

    furnished = bool(re.search(r"gemeubileerd", text, re.I))

    prop_type = _parse_type(text)

    return {
        "source": "123wonen.nl",
        "id": _parse_id(href),
        "url": href,
        "title": f"{prop_type} — {street}, Amsterdam" if street else f"{prop_type} — Amsterdam",
        "street": street,
        "city": "Amsterdam",
        "neighbourhood": neighbourhood,
        "type": prop_type,
        "rent_eur": rent,
        "rent_includes_utilities": bool(re.search(r"incl\.|inclusief", text, re.I)),
        "size_m2": size,
        "furnished": furnished,
        "available_from": _parse_available(text),
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
                if page_num == 1:
                    url = SEARCH_URL
                else:
                    url = f"https://www.123wonen.nl/huurwoningen/in/amsterdam/page/{page_num}?maxhuur=1300&gemeubileerd=1"
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    await page.wait_for_timeout(2500)
                except Exception as e:
                    print(f"  [123wonen] page {page_num} load error: {e}")
                    break

                for _ in range(3):
                    await page.evaluate("window.scrollBy(0, 800)")
                    await page.wait_for_timeout(400)

                cards = await page.evaluate("""() => {
                    const divs = Array.from(document.querySelectorAll('[onclick*="location.href"]'));
                    return divs.map(el => {
                        const m = el.getAttribute('onclick').match(/location\\.href='([^']+)'/);
                        return m ? { href: m[1], text: el.innerText } : null;
                    }).filter(Boolean);
                }""")

                if not cards:
                    print(f"  [123wonen] page {page_num}: no cards found")
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

                print(f"  [123wonen] page {page_num}: {new_on_page} listings")

                # Check for "volgende" (next) link
                has_next = await page.evaluate("""() => {
                    const links = Array.from(document.querySelectorAll('a[href*="/page/"]'));
                    return links.some(a => a.innerText.toLowerCase().includes('volgende'));
                }""")
                if not has_next or new_on_page == 0:
                    break

            await browser.close()

    except Exception as e:
        print(f"  [123wonen] scraper failed: {e}")

    print(f"  [123wonen] total: {len(listings)}")
    return listings


if __name__ == "__main__":
    import json
    results = asyncio.run(scrape())
    print(json.dumps(results[:3], indent=2))
