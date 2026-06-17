"""
Send new Amsterdam listing alerts to jordan@stoke.co.za via Gmail SMTP.
Credentials live in config.py (GMAIL_SENDER + GMAIL_APP_PASSWORD).
"""
import smtplib
from email.message import EmailMessage

try:
    from config import GMAIL_SENDER, GMAIL_APP_PASSWORD, ALERT_RECIPIENT
except ImportError:
    import os
    GMAIL_SENDER = os.environ.get("GMAIL_SENDER", "")
    GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
    ALERT_RECIPIENT = os.environ.get("ALERT_RECIPIENT", "jordan@stoke.co.za")


def _format_listing_text(l: dict) -> str:
    rent = f"€{l['rent_eur']}/mo" if l.get("rent_eur") else "rent unknown"
    size = f"{l['size_m2']}m²" if l.get("size_m2") else ""
    parts = [p for p in [rent, size, l.get("neighbourhood"), l.get("available_from")] if p]
    return (
        f"{l.get('title', 'New listing')}\n"
        f"{'  |  '.join(parts)}\n"
        f"Source: {l.get('source', '')}\n"
        f"{l.get('url', '')}\n"
    )


def _build_email(new_listings: list[dict]) -> EmailMessage:
    count = len(new_listings)
    subject = f"🏠 {count} new Amsterdam listing{'s' if count > 1 else ''} found"

    # Plain-text body
    body_lines = [f"{count} new listing{'s' if count > 1 else ''} found:\n"]
    for i, l in enumerate(new_listings, 1):
        body_lines.append(f"--- {i} ---")
        body_lines.append(_format_listing_text(l))
    text_body = "\n".join(body_lines)

    # HTML body
    html_rows = ""
    for l in new_listings:
        rent = f"€{l['rent_eur']}/mo" if l.get("rent_eur") else "?"
        size = f"{l['size_m2']}m²" if l.get("size_m2") else "?"
        hood = l.get("neighbourhood") or "?"
        avail = l.get("available_from") or "?"
        url = l.get("url", "")
        title = l.get("title", "Listing")
        source = l.get("source", "")
        html_rows += f"""
        <tr>
          <td style="padding:12px 8px;border-bottom:1px solid #eee">
            <strong><a href="{url}" style="color:#1a73e8;text-decoration:none">{title}</a></strong><br>
            <span style="color:#555;font-size:14px">{rent} &nbsp;·&nbsp; {size} &nbsp;·&nbsp; {hood}</span><br>
            <span style="color:#888;font-size:13px">Available: {avail} &nbsp;·&nbsp; {source}</span>
          </td>
        </tr>"""

    html_body = f"""
    <html><body style="font-family:sans-serif;max-width:600px;margin:0 auto;color:#333">
      <h2 style="color:#1a73e8">🏠 {count} new Amsterdam listing{'s' if count > 1 else ''}</h2>
      <table style="width:100%;border-collapse:collapse">
        {html_rows}
      </table>
      <p style="color:#aaa;font-size:12px;margin-top:20px">Amsterdam Housing Scraper</p>
    </body></html>"""

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = GMAIL_SENDER
    msg["To"] = ALERT_RECIPIENT
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")
    return msg


def send_alerts(new_listings: list[dict]) -> int:
    """Send one email containing all new listings. Returns 1 on success, 0 on failure."""
    if not new_listings:
        return 0

    if not GMAIL_SENDER or not GMAIL_APP_PASSWORD:
        print("  [email] GMAIL_SENDER or GMAIL_APP_PASSWORD not set in config.py — skipping alerts")
        return 0

    msg = _build_email(new_listings)
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(GMAIL_SENDER, GMAIL_APP_PASSWORD)
            smtp.send_message(msg)
        print(f"  [email] Alert sent to {ALERT_RECIPIENT} ({len(new_listings)} listing(s))")
        return 1
    except smtplib.SMTPAuthenticationError:
        print("  [email] Authentication failed — check GMAIL_SENDER and GMAIL_APP_PASSWORD in config.py")
        return 0
    except Exception as e:
        print(f"  [email] Failed to send: {e}")
        return 0
