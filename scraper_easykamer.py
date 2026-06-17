"""
Easykamer.nl scraper — rooms and studios in Amsterdam up to €1300.
"""
import re
import asyncio
from datetime import date
from playwright.async_api import async_playwright

SEARCH_URL = (
    "https://www.easykamer.nl/huurwoningen/amsterdam"
    "?maxHuur=1300&gemeubileerd=1"
)
MAX_RENT = 1300
MAX_PAGES = 5


def _parse_id(url: str) -> str:
    # e.g. https://www.easykamer.nl/huurwoning/12345/title
    m = re.search(r"/huurwoning/(\d+)", url)
    if m:
        return f"easykamer-{m.group(1)}"
    # alternative: /kamer/12345
    m2 = re.search(r"/(?:kamer|woning)/(\d+)", url)
    if m2:
        return f"easykamer-{m2.group(1)}"
    # fallback: any number in path
    m3 = re.search(r"/(\d+)/?", url)
    if m3:
        return f"easykamer-{m3.group(1)}"
    return f"easykamer-{url.rstrip('/').split('/')[-1]}"


def _parse_type(url: str, text: str) -> str:
    combined = (url + " " + text).lower()
    if "studio" in combined:
        return "Studio"
    if "appartement" in combined or "apartment" in combined:
        return "Apartment"
    if "kamer" in combined or "room" in combined:
        return "Room"
    return "Unknown"


def _parse_card(href: str, text: str) -> object:
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]

    # Rent: "€ 850 p/m" or "€850 per maand"
    rent_m = re.search(r"€\s*([\d.,]+)\s*(?:p/?m|per\s+maand|/\s*maand)", text, re.I)
    if not rent_m:
        rent_m = re.search(r"€\s*([\d.,]+)", text)
    rent = None
    if rent_m:
        rent = int(rent_m.group(1).replace(".", "").replace(",", ""))

    if rent and rent > MAX_RENT:
        return None

    # Size
    size_m = re.search(r"(\d+)\s*m²", text)
    size = int(size_m.group(1)) if size_m else None

    # Available from: "Per 15 juli 2026" or "Per direct"
    avail = None
    avail_m = re.search(
        r"(?:per|beschikbaar\s+per|vanaf)\s+(\d{1,2}\s+\w+\s+\d{4}|\w+\s+\d{4}|direct)",
        text, re.I,
    )
    if avail_m:
        raw = avail_m.group(1).strip().lower()
        avail = date.today().isoformat() if raw == "direct" else avail_m.group(1).strip()

    # Title — first non-badge line
    badge_words = {"nieuw", "new", "top", "featured", "aanbevolen", "premium"}
    title = next(
        (l for l in lines if l.lower() not in badge_words and not re.match(r"^€", l)),
        "",
    )

    # Neighbourhood
    hood_m = re.search(
        r"\b(jordaan|oud-?zuid|de\s+pijp|oud-?west|oost|west|centrum|noord)\b",
        text + " " + href, re.I,
    )
    neighbourhood = hood_m.group(1).replace("-", " ").title() if hood_m else None

    furnished = bool(re.search(r"gemeubileerd|gestoffeerd|furnished", text, re.I))

    return {
        "source": "easykamer.nl",
        "id": _parse_id(href),
        "url": href,
        "title": title or "Listing — Amsterdam",
        "street": "",
        "city": "Amsterdam",
        "neighbourhood": neighbourhood,
        "type": _parse_type(href, text),
        "rent_eur": rent,
        "rent_includes_utilities": bool(re.search(r"incl\.?\s*(?:gas|water|stroom|utilities|g/w/l)", text, re.I)),
        "size_m2": size,
        "furnished": furnished,
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
                url = SEARCH_URL + (f"&pagina={page_num}" if page_num > 1 else "")
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    await page.wait_for_timeout(2500)
                except Exception as e:
                    print(f"  [easykamer] page {page_num} load error: {e}")
                    break

                cards = await page.evaluate("""() => {
                    // Try multiple link patterns for different site versions
                    const selectors = [
                        'a[href*="/huurwoning/"]',
                        'a[href*="/kamer/"]',
                        'a[href*="/woning/"]',
                    ];
                    const links = new Map();
                    for (const sel of selectors) {
                        for (const a of document.querySelectorAll(sel)) {
                            if (!a.href.includes('amsterdam')) continue;
                            if (!links.has(a.href)) {
                                const card = a.closest('article, [class*="listing"], [class*="card"], [class*="result"], li') || a.parentElement;
                                links.set(a.href, card ? card.innerText : a.innerText);
                            }
                        }
                    }
                    return Array.from(links.entries()).map(([href, text]) => ({ href, text }));
                }""")

                if not cards:
                    print(f"  [easykamer] page {page_num}: no cards found")
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

                print(f"  [easykamer] page {page_num}: {new_on_page} listings")

                has_next = await page.evaluate("""() => {
                    const next = document.querySelector('a[rel="next"], a[aria-label*="next"], a[aria-label*="volgende"], .pagination .next, a.next-page');
                    return !!next;
                }""")
                if not has_next or new_on_page == 0:
                    break

            await browser.close()

    except Exception as e:
        print(f"  [easykamer] scraper failed: {e}")

    print(f"  [easykamer] total: {len(listings)}")
    return listings


if __name__ == "__main__":
    import json
    results = asyncio.run(scrape())
    print(json.dumps(results[:2], indent=2))
