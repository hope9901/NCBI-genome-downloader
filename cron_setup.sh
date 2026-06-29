#!/bin/bash
# cron_setup.sh - Registers the run_pipeline.sh job to the user's crontab.

# Resolve the absolute path of the directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
RUN_SCRIPT="$SCRIPT_DIR/run_pipeline.sh"

# 1. Make the execution wrapper script executable
if [ -f "$RUN_SCRIPT" ]; then
    chmod +x "$RUN_SCRIPT"
    echo "[INFO] Set execution permissions for $RUN_SCRIPT"
else
    echo "[ERROR] $RUN_SCRIPT not found. Please ensure it is present in the directory."
    exit 1
fi

# 2. Define the cron entry (Run daily at 2:00 AM)
# Adjust the cron schedule sequence (minute hour day-of-month month day-of-week) as needed.
CRON_SCHEDULE="0 2 * * *"
CRON_ENTRY="$CRON_SCHEDULE /bin/bash $RUN_SCRIPT"

# 3. Check if this script is already registered in crontab
EXISTING_CRON=$(crontab -l 2>/dev/null)
if echo "$EXISTING_CRON" | grep -F "$RUN_SCRIPT" >/dev/null; then
    echo "[INFO] This pipeline runner is already registered in your crontab."
    echo "[CURRENT CRON ENTRY]:"
    echo "$EXISTING_CRON" | grep -F "$RUN_SCRIPT"
else
    # 4. Append cron entry to existing crontab
    (echo "$EXISTING_CRON"; echo "$CRON_ENTRY") | crontab -
    echo "[SUCCESS] Registered pipeline to crontab."
    echo "[ADDED ENTRY]: $CRON_ENTRY"
    echo "The pipeline will now run automatically every day at 2:00 AM."
fi
