"""
Spotahome.com scraper — furnished rooms, studios, apartments in Amsterdam up to €1300.
"""
import re
import asyncio
from datetime import date
from playwright.async_api import async_playwright

SEARCH_URL = (
    "https://www.spotahome.com/for-rent/amsterdam"
    "?currency=EUR&maxPrice=1300&furnished=true"
)
MAX_RENT = 1300
MAX_PAGES = 5


def _parse_id(url: str) -> str:
    # e.g. https://www.spotahome.com/property/12345-title
    m = re.search(r"/property/(\d+)", url)
    if m:
        return f"spotahome-{m.group(1)}"
    # fallback: last path segment
    slug = url.rstrip("/").split("/")[-1]
    m2 = re.search(r"(\d+)", slug)
    return f"spotahome-{m2.group(1)}" if m2 else f"spotahome-{slug}"


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

    # Rent: "€950/month" or "€950 per month"
    rent_m = re.search(r"€\s*([\d,]+)\s*(?:/\s*month|per\s+month)", text, re.I)
    if not rent_m:
        rent_m = re.search(r"€\s*([\d,]+)", text)
    rent = int(rent_m.group(1).replace(",", "")) if rent_m else None

    if rent and rent > MAX_RENT:
        return None

    # Size: "25 m²" or "25m²"
    size_m = re.search(r"(\d+)\s*m²", text)
    size = int(size_m.group(1)) if size_m else None

    # Available from
    avail = None
    avail_m = re.search(r"(?:available|from)\s+(\d{1,2}\s+\w+\s+\d{4})", text, re.I)
    if avail_m:
        avail = avail_m.group(1)

    # Title: first non-badge line
    badge_words = {"new", "featured", "top", "verified", "sponsored"}
    title = next(
        (l for l in lines if l.lower() not in badge_words and not re.match(r"^€", l)),
        href.split("/")[-1],
    )

    # Neighbourhood: try to extract from title/text (e.g. "in Jordaan")
    hood_m = re.search(
        r"\b(Jordaan|Oud-Zuid|De\s+Pijp|Oud-West|Oost|Amsterdam\s+West|West)\b",
        text, re.I,
    )
    neighbourhood = hood_m.group(1) if hood_m else None

    prop_type = _parse_type(text)

    return {
        "source": "spotahome.com",
        "id": _parse_id(href),
        "url": href,
        "title": title,
        "street": "",
        "city": "Amsterdam",
        "neighbourhood": neighbourhood,
        "type": prop_type,
        "rent_eur": rent,
        "rent_includes_utilities": bool(re.search(r"bills\s+incl|utilities\s+incl", text, re.I)),
        "size_m2": size,
        "furnished": True,  # filter is furnished=true
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
                    print(f"  [spotahome] page {page_num} load error: {e}")
                    break

                # Scroll to load lazy content
                for _ in range(3):
                    await page.evaluate("window.scrollBy(0, 1000)")
                    await page.wait_for_timeout(500)

                cards = await page.evaluate("""() => {
                    // property cards are anchors with /property/ in href
                    const links = Array.from(document.querySelectorAll('a[href*="/property/"]'));
                    const seen = new Set();
                    return links
                        .filter(a => {
                            if (seen.has(a.href)) return false;
                            seen.add(a.href);
                            return true;
                        })
                        .map(a => {
                            const card = a.closest('article, [class*="card"], [class*="Card"], [class*="listing"], li') || a.parentElement;
                            return { href: a.href, text: card ? card.innerText : a.innerText };
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
    print(json.dumps(results[:2], indent=2))
