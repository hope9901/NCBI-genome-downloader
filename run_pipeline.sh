#!/bin/bash
# run_pipeline.sh - Wrapper script for execution via Linux cron daemon.
# This wrapper ensures environment paths are resolved properly under minimal cron contexts.

# Resolve the absolute path of this script's directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# 1. Extend PATH to include common CLI search paths (datasets, python3, conda, local bins)
export PATH=$PATH:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:/home/$USER/.local/bin:/home/$USER/miniconda3/bin:/home/$USER/anaconda3/bin

# 2. Set explicit environment variable for project root
export FUNGI_PROJECT_ROOT="$SCRIPT_DIR"

# 3. Optional: Activate python virtual environment if you configure one in the directory
# if [ -f "$SCRIPT_DIR/venv/bin/activate" ]; then
#     source "$SCRIPT_DIR/venv/bin/activate"
# fi

# 4. Execute the pipeline Python script and redirect standard output/error to a execution log
echo "=== Running Fungi Genome Pipeline: $(date) ===" >> "$SCRIPT_DIR/cron_run.log"
python3 "$SCRIPT_DIR/main.py" >> "$SCRIPT_DIR/cron_run.log" 2>&1

echo "=== Pipeline Execution Finished: $(date) ===" >> "$SCRIPT_DIR/cron_run.log"
