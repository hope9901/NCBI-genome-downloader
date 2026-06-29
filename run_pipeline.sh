#!/bin/bash

# Navigate to the directory where this script is located
cd "$(dirname "$0")"

# Set PATH explicitly to include commonly used locations AND the custom NCBI Datasets CLI path
export PATH="/home/programs/ncbi_datasets:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:$PATH"

# Run the pipeline and log outputs
python3 main.py >> cron_execution.log 2>&1
