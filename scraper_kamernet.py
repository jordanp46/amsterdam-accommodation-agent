"""
Kamernet.nl scraper — rooms, studios, apartments in Amsterdam up to €1300.
Scrapes search result cards (no per-listing page visits).
"""
import re
import asyncio
from datetime import date
from playwright.async_api import async_playwright

SEARCH_URL = (
    "https://kamernet.nl/en/for-rent/properties-amsterdam"
    "?maxRent=1300&minSize=12&furnishing=furnished"
)
MAX_PAGES = 5


def _parse_id(url: str) -> str:
    m = re.search(r"/(room|studio|apartment|house)-(\d+)$", url)
    return f"kamernet-{m.group(2)}" if m else f"kamernet-{url.split('/')[-1]}"


def _parse_type(url: str) -> str:
    for t in ("studio", "apartment", "house", "room"):
        if f"/for-rent/{t}-" in url:
            return t.capitalize()
    return "Unknown"


def _parse_rent(text: str) -> tuple:
    """Returns (rent_eur, includes_utilities)."""
    m = re.search(r"€([\d,]+)", text)
    if not m:
        return None, False
    rent = int(m.group(1).replace(",", ""))
    incl = "incl" in text.lower()
    return rent, incl


def _parse_size(text: str) -> object:
    m = re.search(r"(\d+)\s*m²", text)
    return int(m.group(1)) if m else None


def _parse_dates(text: str) -> tuple:
    """Parse 'From 1 Jul 2026' or '1 Jul - 1 Sep 2026' style dates."""
    months = {
        "Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04",
        "May": "05", "Jun": "06", "Jul": "07", "Aug": "08",
        "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12",
    }
    # Range: "1 Jul - 1 Sep 2026"
    m = re.search(r"(\d+)\s+(\w{3})\s*[-–]\s*(\d+)\s+(\w{3})\s+(\d{4})", text)
    if m:
        d1, mo1, d2, mo2, yr = m.groups()
        avail = f"{yr}-{months.get(mo1, '??')}-{int(d1):02d}"
        until = f"{yr}-{months.get(mo2, '??')}-{int(d2):02d}"
        return avail, until
    # Single date: "From 1 Jul 2026" or "1 Jul 2026"
    m = re.search(r"(\d+)\s+(\w{3})\s+(\d{4})", text)
    if m:
        d, mo, yr = m.groups()
        avail = f"{yr}-{months.get(mo, '??')}-{int(d):02d}"
        return avail, None
    return None, None


def _parse_card(href: str, text: str) -> dict:
    badge_words = {"new", "top ad", "featured", "urgent"}
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    # Skip badge lines to find the street
    street = next((l.rstrip(",") for l in lines if l.lower() not in badge_words and not l.lower().startswith("amsterdam")), "")
    rent, incl = _parse_rent(text)
    size = _parse_size(text)
    avail, until = _parse_dates(text)
    prop_type = _parse_type(href)
    listing_id = _parse_id(href)
    furnished = "furnished" in text.lower()

    return {
        "source": "kamernet.nl",
        "id": listing_id,
        "url": href,
        "title": f"{prop_type} — {street}, Amsterdam" if street else prop_type,
        "street": street,
        "city": "Amsterdam",
        "neighbourhood": None,
        "type": prop_type,
        "rent_eur": rent,
        "rent_includes_utilities": incl,
        "size_m2": size,
        "furnished": furnished,
        "available_from": avail,
        "available_until": until,
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
                       "Chrome/120.0.0.0 Safari/537.36"
        )
        page = await ctx.new_page()

        for page_num in range(1, MAX_PAGES + 1):
            url = SEARCH_URL + (f"&page={page_num}" if page_num > 1 else "")
            await page.goto(url, wait_until="load", timeout=30000)
            await page.wait_for_timeout(2000)

            cards = await page.evaluate("""() => {
                const links = Array.from(document.querySelectorAll('a[href]'))
                    .filter(a => a.href.includes('/for-rent/') && a.href.includes('amsterdam') && !a.href.includes('?'));
                const seen = new Set();
                return links
                    .filter(a => { if (seen.has(a.href)) return false; seen.add(a.href); return true; })
                    .map(a => ({ href: a.href, text: a.innerText }));
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
                if parsed["rent_eur"] and parsed["rent_eur"] <= 1300:
                    listings.append(parsed)
                    new_on_page += 1

            print(f"  [kamernet] page {page_num}: {new_on_page} listings")
            if new_on_page == 0:
                break

        await browser.close()

    print(f"  [kamernet] total: {len(listings)}")
    return listings


if __name__ == "__main__":
    import json
    results = asyncio.run(scrape())
    print(json.dumps(results[:2], indent=2))
