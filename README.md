# Samsung Digital Photo Frame Manager & USB Service

<div align="center">
  <img src="service/static/docs/samsung_spf87h.png" alt="Samsung SPF-87H Digital Photo Frame" width="380" />
  <p><em>Modern Linux USB Controller, Web Scraper & Management Dashboard for Samsung Digital Photo Frames</em></p>
</div>

---

## Overview

This project provides an enterprise-ready daemon and web dashboard to repurpose legacy **Samsung Digital Photo Frames** (e.g., **SPF-87H** and **SPF-107H**) as real-time secondary displays over USB on modern Linux systems.

It continuously captures any user-configured webpage or web dashboard (Home Assistant, Grafana, custom status screens, clocks, weather) using headless Chromium, formats and letterboxes the image to the frame's exact native resolution, and streams it over USB Bulk endpoints.

### Key Capabilities

* **Modern Web Rendering**: Uses Playwright-driven headless Chromium supporting modern CSS Grid, Flexbox, custom webfonts, and client-side JavaScript.
* **Aspect Ratio Calibration**: Automatic scaling with letterboxing (black bars), crop-to-center, or stretch modes powered by Pillow.
* **Self-Healing State Engine**:
  * Automatically detects whether the device is in **Mass Storage Mode** (`0x2033` / `0x2027`) or **Mini-Display Mode** (`0x2034` / `0x2028`).
  * Emits SCSI/USB control commands to switch into Mini-Display mode automatically upon connection.
  * Recovers from USB endpoint stalls (`clear_halt`), pipe errors, and re-enumerations without requiring physical unplugs.
  * Supports optional `virsh` VM USB passthrough re-attachment hooks.
* **Samsung-Branded Web UI**:
  * Follows the Samsung brand design language (Samsung Blue `#034EA2`, crisp white, jet black, and sharp geometry).
  * Real-time WebSocket event logs and status diagnostics.
  * **Verified Live Preview**: The dashboard preview canvas **strictly updates only after confirmation of a successful USB write** to the physical device.

---

## Supported Hardware

| Model | Native Resolution | Mass Storage PID | Display Mode PID |
| :--- | :--- | :--- | :--- |
| **Samsung SPF-87H** | 800 × 480 | `0x2033` | `0x2034` |
| **Samsung SPF-107H** | 1024 × 600 | `0x2027` | `0x2028` |

---

## Directory Structure

```
├── 99-samsung-photoframe.rules  # Udev rules for rootless USB device permissions
├── config.json                  # Persistent service configuration
├── legacy/                      # Archived legacy scripts, Python 2 code, and original zip files
│   ├── samsungframe/            # Previous Dockerfile and scripts
│   └── setup/                   # Setup shell scripts and legacy attempts
├── samsungframe.service         # Systemd service unit file
├── service/
│   ├── config/                  # Configuration models and loaders (Pydantic)
│   ├── driver/                  # USB PyUSB driver and mode-switch logic
│   ├── engine/                  # Playwright capture engine & self-healing supervisor
│   ├── static/docs/             # Product photography and assets
│   ├── templates/               # Samsung-styled web management UI
│   ├── tests/                   # Unit and integration test suites
│   └── main.py                  # FastAPI web server and WebSocket broadcaster
```

---

## Installation & Setup

### 1. Prerequisites (Debian/Ubuntu/Fedora)

Ensure Python 3 and basic USB libraries are installed:
```bash
sudo apt update && sudo apt install -y python3 python3-pip libusb-1.0-0
```

Install Python dependencies and Playwright browser:
```bash
pip install --break-system-packages fastapi uvicorn websockets pyusb pillow playwright
playwright install chromium
```

### 2. Configure USB Permissions (Rootless Access)

To allow the service to communicate with the USB photo frame without needing `root` or `sudo`:

```bash
sudo cp 99-samsung-photoframe.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
```

---

## Usage

### Running Locally / For Testing

Start the application using `uvicorn`:

```bash
python3 -m uvicorn service.main:app --host 0.0.0.0 --port 8080
```

Open your browser at:
👉 **`http://localhost:8080`**

From the dashboard you can:
1. Enter your target URL (e.g. `http://homeassistant.local:8123` or any public dashboard).
2. Adjust the refresh rate (e.g. every 10–30 seconds).
3. Select scaling mode (`Fit & Letterbox`, `Cover & Crop`, `Stretch`).
4. View live hardware status, frames transmitted, and real-time USB event logs.
5. Manually trigger a soft USB reset or mode switch if needed.

### Running as a Background Systemd Service

To keep the service running automatically on system boot:

1. Copy the systemd service file:
   ```bash
   sudo cp samsungframe.service /etc/systemd/system/
   sudo systemctl daemon-reload
   ```

2. Enable and start:
   ```bash
   sudo systemctl enable --now samsungframe.service
   ```

3. Check logs:
   ```bash
   journalctl -u samsungframe.service -f
   ```

---

## Self-Healing & Troubleshooting

* **Frame shows Mass Storage / Mini Monitor prompt**:
  The supervisor automatically sends a USB command (`dev.ctrl_transfer`) to shift into display mode. If it remains stuck, select **"Mini Monitor"** on the frame's touch/side buttons once.
* **USB Permission Denied**:
  Ensure the `99-samsung-photoframe.rules` file is installed in `/etc/udev/rules.d/` and your user belongs to `plugdev` (or relog after reloading udev).
* **Running inside a KVM/QEMU Virtual Machine**:
  If the hypervisor loses USB passthrough upon mode-switch, enter your VM domain name and XML definition path in `config.json` (`virsh_domain` & `virsh_xml_path`). The supervisor will automatically re-attach the USB device upon re-enumeration.

---

## Running Automated Tests

```bash
python3 -m unittest discover -s service/tests
```

