#!/bin/bash
set -e

# Ensure data directories exist
mkdir -p /app/data/documents /app/data/thumbnails /app/data/extractions /app/data/exports

# Start the application — extra args (e.g. --reload) can be passed via CMD
exec uvicorn backend.main:app --host 0.0.0.0 --port 8000 "$@"
