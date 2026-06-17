"""
Spotahome.com scraper — furnished rooms, studios, apartments in Amsterdam up to €1300.
Note: the priceMax URL filter is partially effective; rent cap is enforced in Python.
"""
import re
import asyncio
from datetime import date
from playwright.async_api import async_playwright

SEARCH_URL = (
    "https://www.spotahome.com/s/amsterdam"
    "?priceMax=1300&furnished=true"
)
MAX_RENT = 1300
MAX_PAGES = 5

MONTHS = {
    "january": "01", "february": "02", "march": "03", "april": "04",
    "may": "05", "june": "06", "july": "07", "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12",
}


def _parse_id(url: str) -> str:
    # e.g. https://www.spotahome.com/amsterdam/for-rent:apartments/1436864
    m = re.search(r"/(\d+)$", url.rstrip("/"))
    return f"spotahome-{m.group(1)}" if m else f"spotahome-{url.rstrip('/').split('/')[-1]}"


def _parse_type(url: str) -> str:
    if "for-rent:studios" in url:
        return "Studio"
    if "for-rent:rooms" in url:
        return "Room"
    if "for-rent:apartments" in url:
        return "Apartment"
    return "Unknown"


def _parse_available(text: str) -> object:
    # "FROM 09 SEPTEMBER" or "FROM 9 JUNE"
    m = re.search(r"FROM\s+(\d{1,2})\s+(\w+)", text, re.I)
    if not m:
        return None
    day, month_name = m.group(1), m.group(2).lower()
    mo = MONTHS.get(month_name)
    if not mo:
        return None
    today = date.today()
    year = today.year
    # If this month/day is in the past, it's next year
    try:
        candidate = date(year, int(mo), int(day))
        if candidate < today:
            year += 1
    except ValueError:
        pass
    return f"{year}-{mo}-{int(day):02d}"


def _parse_card(href: str, text: str) -> object:
    # Rent: "6848 €/month" or "€950/month"
    rent_m = re.search(r"([\d,]+)\s*€\s*/\s*month", text, re.I)
    if not rent_m:
        rent_m = re.search(r"€\s*([\d,]+)\s*/\s*month", text, re.I)
    rent = int(rent_m.group(1).replace(",", "")) if rent_m else None

    if rent and rent > MAX_RENT:
        return None

    # Size: "25 m²"
    size_m = re.search(r"(\d+)\s*m²", text)
    size = int(size_m.group(1)) if size_m else None

    # Title: line containing "for rent in"
    title_m = re.search(r"(.+?for rent in .+?)(?:\n|$)", text, re.I)
    title = title_m.group(1).strip() if title_m else _parse_type(href) + " — Amsterdam"

    # Neighbourhood from title "in Burgwallen-Nieuwe Zijde, Amsterdam"
    hood_m = re.search(r"for rent in (.+?),\s*Amsterdam", title, re.I)
    neighbourhood = hood_m.group(1).strip() if hood_m else None

    bills_incl = bool(re.search(r"BILLS INCLUDED", text, re.I))

    return {
        "source": "spotahome.com",
        "id": _parse_id(href),
        "url": href,
        "title": title,
        "street": "",
        "city": "Amsterdam",
        "neighbourhood": neighbourhood,
        "type": _parse_type(href),
        "rent_eur": rent,
        "rent_includes_utilities": bills_incl,
        "size_m2": size,
        "furnished": True,
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
                url = SEARCH_URL + (f"&page={page_num}" if page_num > 1 else "")
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    await page.wait_for_timeout(4000)
                except Exception as e:
                    print(f"  [spotahome] page {page_num} load error: {e}")
                    break

                # Scroll to trigger lazy loading
                for _ in range(5):
                    await page.evaluate("window.scrollBy(0, 900)")
                    await page.wait_for_timeout(600)

                cards = await page.evaluate("""() => {
                    const links = Array.from(document.querySelectorAll('a[href*="/amsterdam/for-rent:"]'))
                        // Only individual listings — URL ends with a numeric ID
                        .filter(a => /\\/\\d+$/.test(a.href.replace(/\\/$/, '')));
                    const seen = new Set();
                    return links
                        .filter(a => { if (seen.has(a.href)) return false; seen.add(a.href); return true; })
                        .map(a => {
                            let el = a;
                            for (let i = 0; i < 8; i++) {
                                el = el.parentElement;
                                if (!el || el.tagName === 'BODY') break;
                                if (el.innerText.trim().length > 50) break;
                            }
                            return { href: a.href, text: el ? el.innerText : a.innerText };
                        });
                }""")

                if not cards:
                    print(f"  [spotahome] page {page_num}: no cards found")
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

                print(f"  [spotahome] page {page_num}: {new_on_page} listings")
                if new_on_page == 0:
                    break

            await browser.close()

    except Exception as e:
        print(f"  [spotahome] scraper failed: {e}")

    print(f"  [spotahome] total: {len(listings)}")
    return listings


if __name__ == "__main__":
    import json
    results = asyncio.run(scrape())
    print(json.dumps(results[:3], indent=2))
