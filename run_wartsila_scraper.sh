#!/bin/bash
# Get the directory where this script is located
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

# Activate virtual environment (assuming standard venv in linux)
source venv/bin/activate

# Run the scraper
python -c "import sys; sys.path.append('$DIR'); from backend.pipeline.wartsila_scraper import fetch_wartsila_routes; fetch_wartsila_routes()"
