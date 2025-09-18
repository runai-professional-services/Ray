#!/bin/bash
# ray.sh — start Ray Serve app

# Exit on error
set -e

# Absolute paths
CONDA_ENV="/home/local/data/env/ray_env"
WORKDIR="/home/local/data"

# Activate conda environment
# (this requires conda to be installed and "conda.sh" init script available)
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate "$CONDA_ENV"

# Change to working directory
cd "$WORKDIR"

# Stop any running Ray cluster first (optional but safe)
ray stop --force || true

# Run Ray Serve with your deploy.py
serve run deploy:app

