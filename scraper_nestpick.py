"""
Nestpick.com scraper — furnished apartments and rooms in Amsterdam up to €1300.
"""
import re
import asyncio
from datetime import date
from playwright.async_api import async_playwright

SEARCH_URL = (
    "https://www.nestpick.com/amsterdam/apartments/"
    "?max_price=1300&furnished=true&sort=relevance"
)
MAX_RENT = 1300
MAX_PAGES = 5


def _parse_id(url: str) -> str:
    # e.g. https://www.nestpick.com/listing/12345
    m = re.search(r"/listing/(\d+)", url)
    if m:
        return f"nestpick-{m.group(1)}"
    m2 = re.search(r"/([a-z0-9-]+-(\d+))/?$", url)
    if m2:
        return f"nestpick-{m2.group(2)}"
    return f"nestpick-{url.rstrip('/').split('/')[-1]}"


def _parse_type(text: str) -> str:
    text_l = text.lower()
    if "studio" in text_l:
        return "Studio"
    if "apartment" in text_l or "flat" in text_l:
        return "Apartment"
    if "room" in text_l:
        return "Room"
    return "Unknown"


def _parse_card(href: str, text: str) -> object:
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]

    # Rent — Nestpick shows "€950/month" or "from €950"
    rent_m = re.search(r"(?:from\s+)?€\s*([\d,]+)\s*(?:/\s*(?:month|mo))?", text, re.I)
    rent = int(rent_m.group(1).replace(",", "")) if rent_m else None

    if rent and rent > MAX_RENT:
        return None

    # Size
    size_m = re.search(r"(\d+)\s*m²", text)
    size = int(size_m.group(1)) if size_m else None

    # Available from
    avail = None
    avail_m = re.search(r"(?:available|from)[:\s]+(\d{1,2}[\s/-]\w+[\s/-]\d{4}|\w+\s+\d{4})", text, re.I)
    if avail_m:
        avail = avail_m.group(1).strip()

    # Title — first meaningful line
    badge_words = {"new", "featured", "popular", "sponsored", "verified"}
    title = next(
        (l for l in lines if l.lower() not in badge_words and not re.match(r"^€", l)),
        "",
    )

    # Neighbourhood
    hood_m = re.search(
        r"\b(Jordaan|Oud-Zuid|De\s+Pijp|Oud-West|Oost|West|Centrum|Noord|Zuid)\b",
        text, re.I,
    )
    neighbourhood = hood_m.group(1) if hood_m else None

    return {
        "source": "nestpick.com",
        "id": _parse_id(href),
        "url": href,
        "title": title or f"Listing — Amsterdam",
        "street": "",
        "city": "Amsterdam",
        "neighbourhood": neighbourhood,
        "type": _parse_type(text),
        "rent_eur": rent,
        "rent_includes_utilities": bool(re.search(r"bills\s+incl|utilities\s+incl|all\s+incl", text, re.I)),
        "size_m2": size,
        "furnished": True,
        "available_from": avail,
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
                    print(f"  [nestpick] page {page_num} load error: {e}")
                    break

                # Scroll to trigger lazy loading
                for _ in range(4):
                    await page.evaluate("window.scrollBy(0, 1000)")
                    await page.wait_for_timeout(600)

                cards = await page.evaluate("""() => {
                    // Nestpick listing cards link to /listing/ or contain a price
                    const selectors = [
                        'a[href*="/listing/"]',
                        'a[href*="/amsterdam/"][href*="-apartment"]',
                        'a[href*="/amsterdam/"][href*="-room"]',
                        'a[href*="/amsterdam/"][href*="-studio"]',
                    ];
                    const links = new Map();
                    for (const sel of selectors) {
                        for (const a of document.querySelectorAll(sel)) {
                            if (!links.has(a.href)) {
                                const card = a.closest('article, [class*="card"], [class*="Card"], [class*="result"], li') || a.parentElement;
                                links.set(a.href, card ? card.innerText : a.innerText);
                            }
                        }
                    }
                    return Array.from(links.entries()).map(([href, text]) => ({ href, text }));
                }""")

                if not cards:
                    print(f"  [nestpick] page {page_num}: no cards found")
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

                print(f"  [nestpick] page {page_num}: {new_on_page} listings")
                if new_on_page == 0:
                    break

            await browser.close()

    except Exception as e:
        print(f"  [nestpick] scraper failed: {e}")

    print(f"  [nestpick] total: {len(listings)}")
    return listings


if __name__ == "__main__":
    import json
    results = asyncio.run(scrape())
    print(json.dumps(results[:2], indent=2))
