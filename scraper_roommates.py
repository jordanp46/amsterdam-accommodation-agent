"""
Roommates.nl scraper — rooms and shared apartments in Amsterdam up to €1300.
"""
import re
import asyncio
from datetime import date
from playwright.async_api import async_playwright

SEARCH_URL = (
    "https://www.roommates.nl/kamers/amsterdam"
    "?maxRent=1300&furnished=1"
)
MAX_RENT = 1300
MAX_PAGES = 5


def _parse_id(url: str) -> str:
    # e.g. https://www.roommates.nl/kamer/12345/title
    m = re.search(r"/kamer/(\d+)", url)
    if m:
        return f"roommates-{m.group(1)}"
    m2 = re.search(r"/(\d+)/?", url)
    if m2:
        return f"roommates-{m2.group(1)}"
    return f"roommates-{url.rstrip('/').split('/')[-1]}"


def _parse_card(href: str, text: str) -> object:
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]

    # Rent: "€ 750 per maand" or "€750/maand"
    rent_m = re.search(r"€\s*([\d.,]+)\s*(?:per\s+maand|/\s*maand|p\.?m\.?)", text, re.I)
    if not rent_m:
        rent_m = re.search(r"€\s*([\d.,]+)", text)
    rent = None
    if rent_m:
        rent = int(rent_m.group(1).replace(".", "").replace(",", ""))

    if rent and rent > MAX_RENT:
        return None

    # Size: "20 m²"
    size_m = re.search(r"(\d+)\s*m²", text)
    size = int(size_m.group(1)) if size_m else None

    # Available from: "Beschikbaar per 1 juli 2026" or "Per direct"
    avail = None
    avail_m = re.search(
        r"(?:beschikbaar\s+per|per|from)\s+(\d{1,2}\s+\w+\s+\d{4}|\w+\s+\d{4}|direct)",
        text, re.I,
    )
    if avail_m:
        raw = avail_m.group(1).strip().lower()
        avail = date.today().isoformat() if raw == "direct" else avail_m.group(1).strip()

    # Title — first non-badge, non-price line
    badge_words = {"nieuw", "new", "top", "featured", "aanbevolen"}
    title = next(
        (l for l in lines if l.lower() not in badge_words and not re.match(r"^€", l)),
        "",
    )

    # Street / neighbourhood from URL slug
    slug = href.rstrip("/").split("/")[-1]
    # e.g. "jordaan-apartment" → "Jordaan"
    hood_m = re.search(
        r"\b(jordaan|oud-?zuid|de-?pijp|oud-?west|oost|west|centrum|noord)\b",
        text + " " + slug, re.I,
    )
    neighbourhood = hood_m.group(1).replace("-", " ").title() if hood_m else None

    furnished = bool(re.search(r"gemeubileerd|gestoffeerd|furnished", text, re.I))

    return {
        "source": "roommates.nl",
        "id": _parse_id(href),
        "url": href,
        "title": title or "Room — Amsterdam",
        "street": "",
        "city": "Amsterdam",
        "neighbourhood": neighbourhood,
        "type": "Room",
        "rent_eur": rent,
        "rent_includes_utilities": bool(re.search(r"incl\.?\s*(?:gas|water|stroom|utilities)", text, re.I)),
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
                url = SEARCH_URL + (f"&page={page_num}" if page_num > 1 else "")
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    await page.wait_for_timeout(2500)
                except Exception as e:
                    print(f"  [roommates] page {page_num} load error: {e}")
                    break

                cards = await page.evaluate("""() => {
                    const links = Array.from(document.querySelectorAll('a[href*="/kamer/"]'));
                    const seen = new Set();
                    return links
                        .filter(a => {
                            if (seen.has(a.href)) return false;
                            seen.add(a.href);
                            return true;
                        })
                        .map(a => {
                            const card = a.closest('article, [class*="listing"], [class*="card"], [class*="result"], li') || a.parentElement;
                            return { href: a.href, text: card ? card.innerText : a.innerText };
                        });
                }""")

                if not cards:
                    print(f"  [roommates] page {page_num}: no cards found")
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

                print(f"  [roommates] page {page_num}: {new_on_page} listings")

                # Check for next page link
                has_next = await page.evaluate("""() => {
                    const next = document.querySelector('a[rel="next"], a[aria-label*="next"], a[aria-label*="volgende"], .pagination .next');
                    return !!next;
                }""")
                if not has_next or new_on_page == 0:
                    break

            await browser.close()

    except Exception as e:
        print(f"  [roommates] scraper failed: {e}")

    print(f"  [roommates] total: {len(listings)}")
    return listings


if __name__ == "__main__":
    import json
    results = asyncio.run(scrape())
    print(json.dumps(results[:2], indent=2))
