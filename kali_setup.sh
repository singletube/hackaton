#!/bin/bash
set -e

echo "=== CloudBridge: Kali Linux Setup Script ==="

# 1. Install System Dependencies
echo "[1/5] Installing system packages (requires sudo)..."
sudo apt update
sudo apt install -y \
    python3 python3-pip python3-venv \
    python3-nautilus fuse3 libfuse3-dev \
    python3-pyfuse3 \
    pkg-config build-essential xclip wl-clipboard \
    python3-tk

# 2. Setup Python Environment
echo "[2/5] Setting up Python virtual environment with system packages..."
# We use --system-site-packages so that the venv can use python3-pyfuse3 and python3-nautilus
# installed via apt, avoiding the need to compile them from source (which fails on Python 3.13).
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
pip install --upgrade pip
# We install only [dev] extras, as [fuse] dependencies are already provided by the system.
pip install -e .[dev]

# 3. Configure Environment
if [ ! -f .env ]; then
    echo "[3/5] Creating .env from example..."
    cp .env.example .env
    echo "!!! IMPORTANT: Edit .env and set your YA_DISK_TOKEN !!!"
else
    echo "[3/5] .env already exists, skipping..."
fi

# 4. Install Nautilus Extension
echo "[4/5] Installing Nautilus context menu extension..."
EXTENSION_DIR="$HOME/.local/share/nautilus-python/extensions"
mkdir -p "$EXTENSION_DIR"

# Get absolute path to venv python and project root
VENV_PYTHON="$(pwd)/.venv/bin/python3"
PROJECT_ROOT="$(pwd)"

# Create a modified version of the extension with absolute paths
cat integrations/nautilus/cloudbridge_extension.py | \
    sed "s|self._python = sys.executable or \"python3\"|self._python = \"$VENV_PYTHON\"|" | \
    sed "s|import sys|import sys; sys.path.append(\"$PROJECT_ROOT\")|" \
    > "$EXTENSION_DIR/cloudbridge_extension.py"

echo "Restarting Nautilus to apply changes..."
nautilus -q || true

# 5. Initialize Database
echo "[5/5] Initializing CloudBridge database..."
python3 -m cloudbridge init-db

echo ""
echo "=== Setup Complete! ==="
echo "1. Don't forget to put your token in the .env file."
echo "2. Run 'source .venv/bin/activate' before using the CLI."
echo "3. Run 'python3 -m cloudbridge discover' to fetch cloud metadata."
echo "4. Use 'python3 -m cloudbridge gui' to open the dashboard."
echo "5. Or use Right-Click (PCM) in Nautilus on any file in your local root."
