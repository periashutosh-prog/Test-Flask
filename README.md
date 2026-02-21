# Cyberdeck OTA Server

A lightweight Flask server for ESP32 over-the-air firmware updates.

## Quick Start

```bash
pip install -r requirements.txt
python app.py
# Server runs on http://0.0.0.0:5000
```

## How It Works

### ESP32 Side
Your device hits the `/ota` endpoint with its current firmware version:

```
GET http://YOUR_SERVER:5000/ota?version=1.00
```

**Responses:**
| Device version | Latest on server | Response                          |
|---------------|-----------------|-----------------------------------|
| < latest      | any             | `200` + firmware `.bin` download  |
| == latest     | any             | `200` + plain text `"Uptodate"`   |
| any           | none uploaded   | `503` + `"No firmware available"` |

### Dashboard (`/`)
- Upload `.bin` files with version numbers
- Set which version is "latest" (what devices receive)
- View SHA-256 checksums for integrity verification
- Delete old builds

### JSON Info endpoint (`/ota/info`)
```json
{
  "latest":   "1.02",
  "sha256":   "abc123...",
  "size":     278528,
  "uploaded": "2025-02-21 09:00 UTC",
  "notes":    "Fixed WiFi reconnect bug"
}
```
Your ESP32 can hit this first to compare SHA before downloading.

## ESP32 Arduino Code

```cpp
#define FIRMWARE_VERSION "1.00"

#include <HTTPClient.h>
#include <HTTPUpdate.h>

void checkOTA() {
  WiFiClient client;
  String url = "http://YOUR_SERVER_IP:5000/ota?version=" + String(FIRMWARE_VERSION);

  HTTPClient http;
  http.begin(url);
  int httpCode = http.GET();

  if (httpCode == HTTP_CODE_OK) {
    String payload = http.getString();
    if (payload == "Uptodate") {
      Serial.println("[OTA] Firmware is current.");
    } else {
      Serial.println("[OTA] Update available! Flashing...");
      http.end();
      // HTTPUpdate handles download + flash + reboot
      t_httpUpdate_return ret = httpUpdate.update(client, "YOUR_SERVER_IP", 5000, "/ota?version=" + String(FIRMWARE_VERSION));
      switch (ret) {
        case HTTP_UPDATE_FAILED:   Serial.println("[OTA] FAILED"); break;
        case HTTP_UPDATE_NO_UPDATES: break;
        case HTTP_UPDATE_OK:       Serial.println("[OTA] OK. Rebooting."); break;
      }
    }
  }
  http.end();
}
```

Call `checkOTA()` at boot, or on a timer.

## File Structure

```
ota-server/
├── app.py              ← Flask server (all logic here)
├── requirements.txt
├── templates/
│   └── index.html      ← Web dashboard
└── firmware/           ← .bin files stored here (auto-created)
    └── meta.json       ← version registry
```

## Roadmap

- [ ] Phase 1 (now): REST endpoint + basic dashboard
- [ ] Phase 2: Multi-device support (different boards / apps)
- [ ] Phase 3: Full web-based .bin flasher UI (drag & drop, progress bar)
- [ ] Phase 4: Standalone `.py` desktop app with auto-discovery
- [ ] Phase 5: Rollback support, staged rollouts, device fleet management

## Deployment Tips

- **Local network**: Run as-is, point ESP at your machine's LAN IP
- **Public**: Put behind nginx + use HTTPS (important for production OTA)
- **Persistent**: Run with `gunicorn app:app` or as a systemd service
- **Docker**: Works fine, just expose port 5000 and mount `./firmware` as a volume
