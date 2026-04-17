#!/bin/bash
set -e

echo "=== CloudBridge Debian/Ubuntu/Kali Setup & Test Script ==="

# 1. Update and install system dependencies
echo "[1/4] Installing system dependencies..."
sudo apt update
# python3-dev and gcc are needed for building some python packages if wheels are missing
# libfuse3-dev and fuse3 are strictly required for pyfuse3
# pkg-config and libglib2.0-dev are needed for GUI integrations
sudo apt install -y python3-pip python3-venv python3-dev gcc libfuse3-dev fuse3 pkg-config libglib2.0-dev libcairo2-dev

# Ensure FUSE module is loaded
sudo modprobe fuse || echo "FUSE module already loaded or not supported in this environment"

# 2. Setup Python virtual environment
echo "[2/4] Setting up Python virtual environment..."
python3 -m venv venv
source venv/bin/activate

# 3. Install Python dependencies
echo "[3/4] Installing Python dependencies..."
pip install --upgrade pip
# Assuming requirements are in pyproject.toml or requirements.txt
# If using pyproject.toml:
pip install -e ".[dev]"
# Explicitly install pyfuse3 and test requirements if not in dev dependencies
pip install pyfuse3 pytest pytest-asyncio

# 4. Run tests
echo "[4/4] Running tests..."
pytest tests/ -v

echo "=== Setup and Testing Complete ==="
echo "To use CloudBridge, activate the environment: source venv/bin/activate"
echo "Then run: cloudbridge --help"
