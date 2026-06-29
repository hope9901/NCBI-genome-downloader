#!/bin/bash

# Navigate to the directory where this script is located
cd "$(dirname "$0")"

# Set basic path explicitly to include default system locations
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:$PATH"

# Run the pipeline and log outputs
# (Custom datasets directory path is resolved dynamically via config.py using the .env variable NCBI_DATASETS_PATH)
python3 main.py >> cron_execution.log 2>&1
