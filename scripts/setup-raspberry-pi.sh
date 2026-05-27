#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

ARCH="$(uname -m)"
if [[ "$ARCH" != "aarch64" && "$ARCH" != "arm64" ]]; then
  echo "Error: Playwright on Linux ARM expects aarch64/arm64."
  echo "Detected architecture: $ARCH"
  echo "Use 64-bit OS (Pi OS 64-bit, Jetson aarch64 Ubuntu, etc.)."
  exit 1
fi

echo "Installing system packages..."
sudo apt-get update
sudo apt-get install -y \
  python3 \
  python3-venv \
  python3-pip \
  git

echo "Installing pipenv via pip..."
python3 -m pip install --user --upgrade pip pipenv
export PATH="$HOME/.local/bin:$PATH"

if [[ ! -f "$ROOT/reserve.env" ]]; then
  cp "$ROOT/reserve.env.example" "$ROOT/reserve.env"
  echo "Created reserve.env — edit it with your Resy URL and NTFY_TOPIC."
fi

echo "Installing Python dependencies..."
pipenv install

echo "Verify Playwright imports (fixes 'No module named playwright' if PATH is wrong)..."
pipenv run python -c "import playwright; print('playwright OK')"

echo "Installing Playwright system libraries (requires sudo)..."
pipenv run playwright install-deps chromium

echo "Installing Chromium for Playwright..."
pipenv run playwright install chromium

echo ""
echo "Setup complete. Next steps:"
echo "  1. Add pipenv to your PATH (if needed):"
echo "       echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.bashrc && source ~/.bashrc"
echo "  2. Edit $ROOT/reserve.env"
echo "  3. Run with the project's venv (do NOT use bare python3 reserve.py):"
echo "       cd $ROOT && .venv/bin/python reserve.py"
echo "       # or:  pipenv run python reserve.py"
echo ""
echo "Optional — run on boot with systemd:"
echo "  sudo sed \"s|/home/pi/alert|$ROOT|g\" reserve.service | sudo tee /etc/systemd/system/reserve.service"
echo "  sudo systemctl daemon-reload"
echo "  sudo systemctl enable --now reserve.service"
echo "  journalctl -u reserve.service -f"
