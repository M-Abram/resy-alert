#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

ARCH="$(uname -m)"
if [[ "$ARCH" != "aarch64" && "$ARCH" != "arm64" ]]; then
  echo "Error: Playwright needs 64-bit Raspberry Pi OS (aarch64)."
  echo "Detected architecture: $ARCH"
  echo "Use Raspberry Pi OS (64-bit) from the imager, not the 32-bit build."
  exit 1
fi

echo "Installing system packages..."
sudo apt-get update
sudo apt-get install -y \
  python3 \
  python3-venv \
  python3-pip \
  pipenv \
  git

if [[ ! -f "$ROOT/reserve.env" ]]; then
  cp "$ROOT/reserve.env.example" "$ROOT/reserve.env"
  echo "Created reserve.env — edit it with your Resy URL and NTFY_TOPIC."
fi

echo "Installing Python dependencies..."
pipenv install

echo "Installing Playwright system libraries (requires sudo)..."
pipenv run playwright install-deps chromium

echo "Installing Chromium for Playwright..."
pipenv run playwright install chromium

echo ""
echo "Setup complete. Next steps:"
echo "  1. Edit $ROOT/reserve.env"
echo "  2. Test:  cd $ROOT && set -a && source reserve.env && set +a && .venv/bin/python reserve.py"
echo ""
echo "Optional — run on boot with systemd:"
echo "  sudo sed \"s|/home/pi/alert|$ROOT|g\" reserve.service | sudo tee /etc/systemd/system/reserve.service"
echo "  sudo systemctl daemon-reload"
echo "  sudo systemctl enable --now reserve.service"
echo "  journalctl -u reserve.service -f"
