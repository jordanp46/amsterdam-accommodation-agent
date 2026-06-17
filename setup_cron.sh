#!/bin/bash
# Add a cron job to run the Amsterdam scraper every 3 hours.
# Run once: bash setup_cron.sh
# To remove: crontab -e and delete the line.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON=$(which python3)
CRON_LINE="0 */3 * * * cd $SCRIPT_DIR && $PYTHON run.py >> $SCRIPT_DIR/scraper.log 2>&1"

# Check if already added
if crontab -l 2>/dev/null | grep -q "amsterdam-scraper"; then
    echo "Cron job already exists."
else
    (crontab -l 2>/dev/null; echo "$CRON_LINE") | crontab -
    echo "Cron job added: runs every 3 hours."
    echo "Logs will appear in: $SCRIPT_DIR/scraper.log"
fi

echo ""
echo "Current crontab:"
crontab -l
