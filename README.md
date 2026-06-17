# Amsterdam Accommodation Agent

Scrapes Kamernet.nl, Pararius.nl, and HousingAnywhere.com for Amsterdam rentals, tracks seen listings in a SQLite database, and emails new listings to your inbox as soon as they appear.

## What it does

1. **Scrapes** three Amsterdam rental platforms and outputs a unified `listings.json`
2. **Deduplicates** across sources using listing IDs
3. **Tracks** every seen listing in `listings.db` so repeat runs only surface genuinely new ones
4. **Alerts** — sends a batched HTML email for each new listing found

## Project structure

```
amsterdam-scraper/
├── run.py              # CLI runner — one command to trigger a full scrape cycle
├── db.py               # SQLite store (listings.db) for seen-listing tracking
├── email_alert.py      # Gmail SMTP alert sender
├── config.example.py   # Credentials template — copy to config.py and fill in
├── setup_cron.sh       # Optional: schedule automatic runs every 3 hours
├── listings.db         # SQLite database (auto-created on first run)
└── listings.json       # Output from the scraper (placed in parent directory)
```

## Setup

### 1. Install dependencies

```bash
pip3 install requests
```

### 2. Configure credentials

```bash
cp config.example.py config.py
```

Edit `config.py`:

```python
GMAIL_SENDER = "you@gmail.com"       # Gmail address to send from
GMAIL_APP_PASSWORD = ""              # 16-char App Password from myaccount.google.com/apppasswords
ALERT_RECIPIENT = "you@example.com"  # Where to send alerts
LISTINGS_JSON = "/path/to/listings.json"
```

> **App Password**: Go to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords) (requires 2-Step Verification). Create one named "Amsterdam Scraper" and paste the 16-character code.

### 3. Run

```bash
# Normal run — detect new listings, save to DB, send email alert
python3 run.py

# Preview new listings without saving or alerting
python3 run.py --dry-run

# Show how many listings are tracked in the DB
python3 run.py --stats

# Use a custom listings.json path
python3 run.py --json /path/to/listings.json
```

### 4. Automate (optional)

```bash
bash setup_cron.sh
```

Adds a cron job that runs every 3 hours and logs output to `scraper.log`.

## Filters applied

- City: Amsterdam
- Max rent: €1,300/mo
- Min size: 12m²
- Furnished only
- Available from: 2026-07-15
- Property types: Room, Studio, Apartment
- Target neighbourhoods: Jordaan, Oud-Zuid, West, De Pijp, Oud-West, Oost
