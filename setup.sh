#!/bin/bash
set -e

echo "=========================================================="
echo " Samsung Photo Frame Controller & USB Service Setup"
echo "=========================================================="

# 1. Install Udev rules
echo "[1/3] Installing udev rules for rootless USB device access..."
if [ -d "/etc/udev/rules.d" ]; then
    sudo cp 99-samsung-photoframe.rules /etc/udev/rules.d/
    sudo udevadm control --reload-rules && sudo udevadm trigger
    echo "      ✓ Udev rules installed and reloaded."
else
    echo "      ! /etc/udev/rules.d not found. Skipping udev copy."
fi

# 2. Check dependencies
echo "[2/3] Checking dependencies..."
python3 -c "import fastapi, uvicorn, websockets, usb.core, PIL, playwright" 2>/dev/null || {
    echo "      Installing required Python packages..."
    python3 -m pip install --user --break-system-packages fastapi uvicorn websockets pyusb pillow playwright
    python3 -m playwright install chromium
}
echo "      ✓ Python packages and Chromium are installed."

# 3. Setup systemd service (optional)
echo "[3/3] Setting up systemd service..."
if [ -d "/etc/systemd/system" ]; then
    read -p "Would you like to install and enable samsungframe.service now? [y/N]: " ENABLE_SVC
    if [[ "$ENABLE_SVC" =~ ^[Yy]$ ]]; then
        sudo cp samsungframe.service /etc/systemd/system/
        sudo systemctl daemon-reload
        sudo systemctl enable --now samsungframe.service
        echo "      ✓ Service enabled and started! Status: sudo systemctl status samsungframe.service"
    else
        echo "      Skipped systemd installation."
    fi
fi

echo "=========================================================="
echo " Setup complete! To run the service manually:"
echo "   python3 -m uvicorn service.main:app --host 0.0.0.0 --port 8080"
echo " Open Web UI at: http://localhost:8080"
echo "=========================================================="
