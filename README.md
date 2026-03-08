# UniFi Network & Protect Integration for Unfolded Circle Remote

[![GitHub Release](https://img.shields.io/github/v/release/mase1981/uc-intg-unifi?style=flat-square)](https://github.com/mase1981/uc-intg-unifi/releases)
![License](https://img.shields.io/badge/license-MPL--2.0-blue?style=flat-square)
[![GitHub issues](https://img.shields.io/github/issues/mase1981/uc-intg-unifi?style=flat-square)](https://github.com/mase1981/uc-intg-unifi/issues)
[![Community Forum](https://img.shields.io/badge/community-forum-blue?style=flat-square)](https://unfolded.community/)
[![Discord](https://badgen.net/discord/online-members/zGVYf58)](https://discord.gg/zGVYf58)
![GitHub Downloads](https://img.shields.io/github/downloads/mase1981/uc-intg-unifi/total?style=flat-square)
[![Buy Me A Coffee](https://img.shields.io/badge/buy%20me%20a%20coffee-donate-yellow.svg?style=flat-square)](https://buymeacoffee.com/meirmiyara)
[![PayPal](https://img.shields.io/badge/PayPal-donate-blue.svg?style=flat-square)](https://paypal.me/mmiyara)
[![Github Sponsors](https://img.shields.io/badge/GitHub%20Sponsors-30363D?&logo=GitHub-Sponsors&logoColor=EA4AAA&style=flat-square)](https://github.com/sponsors/mase1981)

Control your UniFi Network and Protect devices from your Unfolded Circle Remote with WiFi network management, PoE port control, WAN monitoring, and camera integration.

---

## Support Development

[![GitHub Sponsors](https://img.shields.io/badge/Sponsor-GitHub-pink?style=for-the-badge&logo=github)](https://github.com/sponsors/mase1981)
[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-FFDD00?style=for-the-badge&logo=buy-me-a-coffee&logoColor=black)](https://www.buymeacoffee.com/meirmiyara)
[![PayPal](https://img.shields.io/badge/PayPal-00457C?style=for-the-badge&logo=paypal&logoColor=white)](https://paypal.me/mmiyara)

---

## Supported Devices

| Console | Auth Method | Features |
|---------|------------|----------|
| UniFi Dream Machine (UDM) | Username/Password | Network + Protect |
| UniFi Dream Machine Pro (UDM Pro) | Username/Password | Network + Protect |
| UniFi Dream Machine SE (UDM SE) | Username/Password | Network + Protect |
| UniFi Cloud Key Gen2+ | Username/Password | Network + Protect |
| Self-hosted Controller | Username/Password | Network only |

> **Note:** Local administrator accounts only. Cloud/SSO accounts are not supported.

---

## Sensors

Real-time monitoring of WAN and network status.

| Sensor | Description |
|--------|-------------|
| WAN Status | Connection status, public IP, uptime |
| WAN Download | Current download speed (Mbps/Gbps) |
| WAN Upload | Current upload speed (Mbps/Gbps) |
| Connected Clients | Total number of connected clients |

---

## Select Entities

Dropdown controls for PoE port management.

| Select | Description |
|--------|-------------|
| PoE On | Enable PoE on any port |
| PoE Off | Disable PoE on any port |

Port options are dynamically populated with all PoE-capable ports across your network devices.

---

## Remote Commands

Available through remote entity UI pages.

| Page | Commands |
|------|----------|
| WiFi | Enable/Disable each WiFi network |
| Guest | Enable/Disable guest networks |
| Devices | Reboot any network device |

---

## Camera Entities (Protect)

Automatically discovered when UniFi Protect is available.

| Entity | Description |
|--------|-------------|
| Camera | Live view and snapshot |
| Motion Sensor | Motion detection binary sensor |
| Privacy Switch | Enable/disable privacy mode |
| Recording Mode | Select recording mode |
| IR Mode | Select infrared LED mode |
| Reboot Button | Restart camera |
| Floodlight | Control floodlight (supported cameras) |

---

## Installation

### Option 1: Remote Web Interface (Recommended)

1. Download the latest `.tar.gz` from [Releases](https://github.com/mase1981/uc-intg-unifi/releases)
2. Open Remote web interface → **Settings** → **Integrations**
3. Click **Upload** and select the downloaded file
4. Configure: Enter UniFi Console IP, username, and password
5. Done - entities are created automatically

### Option 2: Docker (Advanced Users)

The integration is available as a pre-built Docker image from GitHub Container Registry:

**Image**: `ghcr.io/mase1981/uc-intg-unifi:latest`

**Docker Compose:**
```yaml
services:
  uc-intg-unifi:
    image: ghcr.io/mase1981/uc-intg-unifi:latest
    container_name: uc-intg-unifi
    network_mode: host
    volumes:
      - </local/path>:/data
    environment:
      - UC_CONFIG_HOME=/data
      - UC_INTEGRATION_HTTP_PORT=9030
      - UC_INTEGRATION_INTERFACE=0.0.0.0
      - PYTHONPATH=/app
    restart: unless-stopped
```

**Docker Run:**
```bash
docker run -d --name uc-unifi --restart unless-stopped --network host -v unifi-config:/app/config -e UC_CONFIG_HOME=/app/config -e UC_INTEGRATION_INTERFACE=0.0.0.0 -e UC_INTEGRATION_HTTP_PORT=9030 -e PYTHONPATH=/app ghcr.io/mase1981/uc-intg-unifi:latest
```

**Requirements:**
- UniFi Console on same network
- Local administrator account (not cloud/SSO)
- Static IP recommended

---

## License

Mozilla Public License 2.0 (MPL-2.0)

## Links

- [GitHub Issues](https://github.com/mase1981/uc-intg-unifi/issues)
- [UC Community Forum](https://unfolded.community/)
- [Discord](https://discord.gg/zGVYf58)
- [UniFi Support](https://help.ui.com/)

---

**Made with care for the Unfolded Circle and UniFi communities**
