"""UniFi device - Proper session-based authentication like Home Assistant aiounifi."""
import logging
import ssl
from http import cookies
from typing import Any

import aiohttp
from ucapi_framework import DeviceEvents, PollingDevice

from intg_unifi.config import UniFiConfig

_LOG = logging.getLogger(__name__)

# Patch for UniFi OS partitioned cookie support (required for modern UniFi OS)
if "partitioned" not in cookies.Morsel._reserved:
    cookies.Morsel._reserved["partitioned"] = "partitioned"
    cookies.Morsel._flags.add("partitioned")


class UniFiDevice(PollingDevice):
    """UniFi Console device with proper session-based authentication.

    Based on Home Assistant's aiounifi library approach:
    - Properly captures CSRF token and session cookies from login
    - Includes auth headers in ALL subsequent requests
    - Works with both UniFi OS (UDM) and traditional controllers
    """

    def __init__(self, device_config: UniFiConfig, **kwargs):
        """Initialize UniFi device."""
        super().__init__(device_config, poll_interval=15, **kwargs)
        self._device_config = device_config
        self._session: aiohttp.ClientSession | None = None
        self._is_connected = False

        # Auth state
        self._auth_headers: dict[str, str] = {}
        self._is_unifi_os = False

        # Data storage
        self._network_devices: dict[str, Any] = {}
        self._wlans: dict[str, Any] = {}
        self._ports: dict[str, list[Any]] = {}
        self._clients: dict[str, Any] = {}

        # Site info
        self._site_id: str = "default"
        self._site_name: str = "default"

        # Gateway for WAN stats
        self._gateway_device: dict[str, Any] | None = None
        self._wan_health: dict[str, Any] = {}

        # Protect data
        self._cameras: dict[str, Any] = {}
        self._has_protect: bool = False

        # Auth mode
        self._use_api_key = bool(device_config.api_key)

    @property
    def identifier(self) -> str:
        return self._device_config.identifier

    @property
    def name(self) -> str:
        return self._device_config.name

    @property
    def address(self) -> str:
        return self._device_config.host

    @property
    def log_id(self) -> str:
        return f"{self.name} ({self.address})"

    @property
    def is_connected(self) -> bool:
        return self._is_connected

    @property
    def state(self) -> str | None:
        if self._is_connected:
            return "ON"
        return "OFF"

    @property
    def network_devices(self) -> dict[str, Any]:
        return self._network_devices

    @property
    def wlans(self) -> dict[str, Any]:
        return self._wlans

    @property
    def ports(self) -> dict[str, list[Any]]:
        return self._ports

    @property
    def clients(self) -> dict[str, Any]:
        return self._clients

    @property
    def client_count(self) -> int:
        return len(self._clients)

    @property
    def cameras(self) -> dict[str, Any]:
        return self._cameras

    @property
    def has_protect(self) -> bool:
        return self._has_protect

    @property
    def gateway(self) -> dict[str, Any] | None:
        return self._gateway_device

    async def establish_connection(self) -> None:
        """Connect to UniFi Console."""
        _LOG.info("[%s] Connecting to UniFi Console", self.log_id)

        ssl_context: ssl.SSLContext | bool = False
        if self._device_config.verify_ssl:
            ssl_context = ssl.create_default_context()

        connector = aiohttp.TCPConnector(ssl=ssl_context)
        timeout = aiohttp.ClientTimeout(total=30)
        self._session = aiohttp.ClientSession(connector=connector, timeout=timeout)

        try:
            if self._use_api_key:
                await self._connect_api_key()
            else:
                await self._connect_credentials()

            self._is_connected = True
            self.events.emit(DeviceEvents.CONNECTED, self.identifier)
            _LOG.info("[%s] Connected successfully", self.log_id)

            self._emit_updates()

        except Exception as err:
            _LOG.error("[%s] Connection failed: %s", self.log_id, err)
            if self._session:
                await self._session.close()
                self._session = None
            raise ConnectionError(f"Failed to connect: {err}") from err

    async def _check_unifi_os(self) -> None:
        """Check if controller is running UniFi OS (UDM, Cloud Key Gen2+)."""
        self._is_unifi_os = False
        url = f"https://{self.address}"
        try:
            async with self._session.get(url, allow_redirects=False) as resp:
                if resp.status == 200:
                    self._is_unifi_os = True
                    self._session.cookie_jar.clear_domain(self.address)
                    _LOG.info("[%s] Detected UniFi OS controller", self.log_id)
                else:
                    _LOG.info("[%s] Detected traditional controller (status=%d)", self.log_id, resp.status)
        except Exception as err:
            _LOG.debug("[%s] UniFi OS check error: %s", self.log_id, err)

    async def _connect_api_key(self) -> None:
        """Connect using API key with Integration API."""
        _LOG.info("[%s] Using API key authentication", self.log_id)

        self._auth_headers = {"X-API-KEY": self._device_config.api_key}

        sites = await self._api_get("/proxy/network/integration/v1/sites")
        if sites:
            site_list = sites if isinstance(sites, list) else sites.get("data", [])
            if site_list:
                first = site_list[0] if isinstance(site_list[0], dict) else {}
                self._site_id = first.get("id", "default")
                self._site_name = first.get("name", "default")
                _LOG.info("[%s] Using site: %s (ID: %s)", self.log_id, self._site_name, self._site_id)

        await self._fetch_data_integration_api()
        await self._fetch_protect()

    async def _connect_credentials(self) -> None:
        """Connect using username/password with proper session handling."""
        _LOG.info("[%s] Using username/password authentication", self.log_id)

        if not self._device_config.username or not self._device_config.password:
            raise ConnectionError("Username and password required")

        await self._check_unifi_os()

        self._auth_headers = {}

        login_url = f"https://{self.address}/api"
        login_url += "/auth/login" if self._is_unifi_os else "/login"

        login_data = {
            "username": self._device_config.username,
            "password": self._device_config.password,
            "rememberMe": True,
        }

        try:
            async with self._session.post(login_url, json=login_data) as resp:
                _LOG.debug("[%s] Login response status: %d", self.log_id, resp.status)

                if resp.status != 200:
                    body = await resp.text()
                    _LOG.error("[%s] Login failed with status %d: %s", self.log_id, resp.status, body[:200])
                    raise ConnectionError(f"Login failed: {resp.status}")

                if csrf_token := resp.headers.get("x-csrf-token"):
                    self._auth_headers["x-csrf-token"] = csrf_token
                    _LOG.debug("[%s] Captured CSRF token", self.log_id)

                if set_cookie := resp.headers.get("Set-Cookie"):
                    self._auth_headers["Cookie"] = set_cookie.split(";")[0]
                    _LOG.debug("[%s] Captured session cookie", self.log_id)

                _LOG.info("[%s] Login successful (CSRF=%s, Cookie=%s)",
                         self.log_id,
                         "yes" if "x-csrf-token" in self._auth_headers else "no",
                         "yes" if "Cookie" in self._auth_headers else "no")

        except aiohttp.ClientError as err:
            _LOG.error("[%s] Login request failed: %s", self.log_id, err)
            raise ConnectionError(f"Login failed: {err}") from err

        sites = await self._api_get("/proxy/network/api/self/sites" if self._is_unifi_os else "/api/self/sites")
        if sites and isinstance(sites, dict):
            data = sites.get("data", [])
            if data:
                self._site_name = data[0].get("name", "default") if isinstance(data[0], dict) else "default"
                _LOG.info("[%s] Using site: %s", self.log_id, self._site_name)

        await self._fetch_data_controller_api()
        await self._fetch_protect()

    def _get_headers(self) -> dict[str, str]:
        """Get request headers including auth."""
        headers = {"Content-Type": "application/json"}
        headers.update(self._auth_headers)
        return headers

    async def _api_get(self, path: str) -> dict | list | None:
        """Make GET request with auth headers."""
        if not self._session:
            return None
        url = f"https://{self.address}{path}"
        try:
            async with self._session.get(url, headers=self._get_headers()) as resp:
                if resp.status == 200:
                    return await resp.json()
                _LOG.warning("[%s] GET %s returned %d", self.log_id, path, resp.status)
        except Exception as err:
            _LOG.warning("[%s] GET %s failed: %s", self.log_id, path, err)
        return None

    async def _api_post(self, path: str, data: dict | None = None) -> bool:
        """Make POST request with auth headers."""
        if not self._session:
            _LOG.error("[%s] POST %s failed: no session", self.log_id, path)
            return False
        url = f"https://{self.address}{path}"
        try:
            async with self._session.post(url, json=data or {}, headers=self._get_headers()) as resp:
                if resp.status in (200, 201, 204):
                    return True
                body = await resp.text()
                _LOG.warning("[%s] POST %s returned %d: %s", self.log_id, path, resp.status, body[:200])
                return False
        except Exception as err:
            _LOG.warning("[%s] POST %s failed: %s", self.log_id, path, err)
        return False

    async def _api_put(self, path: str, data: dict | None = None) -> bool:
        """Make PUT request with auth headers."""
        if not self._session:
            _LOG.error("[%s] PUT %s failed: no session", self.log_id, path)
            return False
        url = f"https://{self.address}{path}"
        try:
            async with self._session.put(url, json=data or {}, headers=self._get_headers()) as resp:
                if resp.status in (200, 201, 204):
                    return True
                body = await resp.text()
                _LOG.warning("[%s] PUT %s returned %d: %s", self.log_id, path, resp.status, body[:200])
                return False
        except Exception as err:
            _LOG.warning("[%s] PUT %s failed: %s", self.log_id, path, err)
        return False

    async def _api_patch(self, path: str, data: dict | None = None) -> bool:
        """Make PATCH request with auth headers."""
        if not self._session:
            _LOG.error("[%s] PATCH %s failed: no session", self.log_id, path)
            return False
        url = f"https://{self.address}{path}"
        try:
            async with self._session.patch(url, json=data or {}, headers=self._get_headers()) as resp:
                if resp.status in (200, 201, 204):
                    return True
                body = await resp.text()
                _LOG.warning("[%s] PATCH %s returned %d: %s", self.log_id, path, resp.status, body[:200])
                return False
        except Exception as err:
            _LOG.warning("[%s] PATCH %s failed: %s", self.log_id, path, err)
        return False

    async def _fetch_data_integration_api(self) -> None:
        """Fetch data using Integration API (for API key mode)."""
        base = f"/proxy/network/integration/v1/sites/{self._site_id}"

        self._network_devices = {}
        self._ports = {}
        self._gateway_device = None

        devices = await self._api_get(f"{base}/devices?limit=100")
        device_list = devices if isinstance(devices, list) else (devices.get("data", []) if devices else [])

        for dev in device_list:
            if not isinstance(dev, dict):
                continue

            dev_id = dev.get("id", "")
            if not dev_id:
                continue

            self._network_devices[dev_id] = dev

            model = (dev.get("model") or "").lower()
            if "dream machine" in model or "udm" in model:
                self._gateway_device = dev
                _LOG.info("[%s] Found gateway: %s (IP: %s)", self.log_id,
                         dev.get("name", "Unknown"), dev.get("ipAddress", "N/A"))

        _LOG.info("[%s] Found %d devices from list", self.log_id, len(self._network_devices))

        for dev_id in list(self._network_devices.keys()):
            details = await self._api_get(f"{base}/devices/{dev_id}")
            if details and isinstance(details, dict):
                self._network_devices[dev_id].update(details)

                interfaces = details.get("interfaces", {})
                ports = interfaces.get("ports", [])
                if ports and isinstance(ports, list):
                    self._ports[dev_id] = ports
                    poe_count = sum(1 for p in ports if isinstance(p, dict) and
                                   p.get("poe", {}).get("enabled", False))
                    _LOG.debug("[%s] Device %s: %d ports (%d PoE)",
                              self.log_id, details.get("name", dev_id), len(ports), poe_count)

        _LOG.info("[%s] Loaded %d devices, %d with ports, gateway=%s",
                  self.log_id, len(self._network_devices), len(self._ports),
                  "found" if self._gateway_device else "not found")

        clients = await self._api_get(f"{base}/clients?limit=200")
        client_list = clients if isinstance(clients, list) else (clients.get("data", []) if clients else [])
        self._clients = {}
        for c in client_list:
            if isinstance(c, dict):
                cid = c.get("mac") or c.get("id")
                if cid:
                    self._clients[cid] = c
        _LOG.info("[%s] Loaded %d clients", self.log_id, len(self._clients))

    async def _fetch_data_controller_api(self) -> None:
        """Fetch data using Controller API (for username/password mode)."""
        if self._is_unifi_os:
            base = f"/proxy/network/api/s/{self._site_name}"
        else:
            base = f"/api/s/{self._site_name}"

        self._network_devices = {}
        self._ports = {}
        self._gateway_device = None

        devices = await self._api_get(f"{base}/stat/device")
        device_list = devices.get("data", []) if isinstance(devices, dict) else (devices if isinstance(devices, list) else [])

        for dev in device_list:
            if not isinstance(dev, dict):
                continue

            mac = dev.get("mac", "")
            if not mac:
                continue

            self._network_devices[mac] = dev

            ports = dev.get("port_table", [])
            if ports and isinstance(ports, list):
                self._ports[mac] = ports
                poe_count = sum(1 for p in ports if isinstance(p, dict) and self._is_poe_port(p))
                _LOG.debug("[%s] Device %s has %d ports (%d PoE)",
                          self.log_id, dev.get("name", mac), len(ports), poe_count)

            dev_type = (dev.get("type") or "").lower()
            if dev_type in ("ugw", "udm", "uxg", "usg"):
                self._gateway_device = dev
                _LOG.info("[%s] Found gateway: %s", self.log_id, dev.get("name", "Unknown"))

        _LOG.info("[%s] Loaded %d devices, %d with ports, gateway=%s",
                  self.log_id, len(self._network_devices), len(self._ports),
                  "found" if self._gateway_device else "not found")

        wlans = await self._api_get(f"{base}/rest/wlanconf")
        wlan_list = wlans.get("data", []) if isinstance(wlans, dict) else (wlans if isinstance(wlans, list) else [])
        self._wlans = {}
        for w in wlan_list:
            if isinstance(w, dict):
                wid = w.get("_id")
                if wid:
                    self._wlans[wid] = w
        _LOG.info("[%s] Loaded %d WLANs", self.log_id, len(self._wlans))

        clients = await self._api_get(f"{base}/stat/sta")
        client_list = clients.get("data", []) if isinstance(clients, dict) else (clients if isinstance(clients, list) else [])
        self._clients = {}
        for c in client_list:
            if isinstance(c, dict):
                mac = c.get("mac")
                if mac:
                    self._clients[mac] = c
        _LOG.info("[%s] Loaded %d clients", self.log_id, len(self._clients))

        await self._fetch_health(base)

    async def _fetch_health(self, base: str) -> None:
        """Fetch site health data including WAN throughput."""
        self._wan_health = {}

        health = await self._api_get(f"{base}/stat/health")
        health_list = health.get("data", []) if isinstance(health, dict) else (health if isinstance(health, list) else [])

        for subsystem in health_list:
            if isinstance(subsystem, dict) and subsystem.get("subsystem") == "wan":
                self._wan_health = subsystem
                rx_rate = subsystem.get("rx_bytes-r", 0)
                tx_rate = subsystem.get("tx_bytes-r", 0)
                _LOG.info("[%s] WAN health: rx=%d B/s, tx=%d B/s, ip=%s",
                         self.log_id, rx_rate, tx_rate, subsystem.get("wan_ip", "N/A"))
                break

    async def _fetch_protect(self) -> None:
        """Fetch UniFi Protect cameras."""
        response = await self._api_get("/proxy/protect/api/cameras")

        self._cameras = {}
        self._has_protect = False

        if not response:
            return

        cam_list = response if isinstance(response, list) else response.get("data", [])
        for cam in cam_list:
            if isinstance(cam, dict):
                cid = cam.get("id")
                if cid:
                    self._cameras[cid] = cam

        if self._cameras:
            self._has_protect = True
            _LOG.info("[%s] Loaded %d cameras from Protect", self.log_id, len(self._cameras))

    def _is_poe_port(self, port: dict) -> bool:
        """Check if port has PoE capability."""
        poe = port.get("poe")
        if isinstance(poe, dict):
            return poe.get("enabled", False) or poe.get("state") == "UP"
        if port.get("port_poe"):
            return True
        poe_mode = port.get("poe_mode", "")
        if poe_mode and poe_mode != "off":
            return True
        if port.get("poe_caps", 0) > 0:
            return True
        return False

    async def disconnect(self) -> None:
        """Disconnect from UniFi Console and stop polling."""
        _LOG.info("[%s] Disconnecting", self.log_id)
        await super().disconnect()
        if self._session:
            await self._session.close()
            self._session = None
        self._is_connected = False
        self._auth_headers = {}
        self.events.emit(DeviceEvents.DISCONNECTED, self.identifier)

    async def poll_device(self) -> None:
        """Poll device for updates. Emits per-entity UPDATE events."""
        if not self._is_connected:
            _LOG.debug("[%s] Not connected, attempting reconnection", self.log_id)
            try:
                await self.establish_connection()
                _LOG.info("[%s] Reconnected successfully during poll", self.log_id)
            except Exception as err:
                _LOG.debug("[%s] Reconnection failed: %s", self.log_id, err)
                return

        try:
            if self._use_api_key:
                await self._fetch_data_integration_api()
            else:
                await self._fetch_data_controller_api()
            if self._has_protect:
                await self._fetch_protect()

            self._emit_updates()

        except Exception as err:
            _LOG.warning("[%s] Poll failed: %s", self.log_id, err)
            self._is_connected = False
            self.events.emit(DeviceEvents.DISCONNECTED, self.identifier)

    def _emit_updates(self) -> None:
        """Emit per-entity UPDATE events with proper entity_id and attributes.

        Each entity gets its own UPDATE event with both state AND value.
        This is required by ucapi-framework for proper entity state propagation
        and reboot survival.
        """
        ident = self._device_config.identifier
        state = "ON" if self._is_connected else "OFF"

        # Remote entity
        self.events.emit(DeviceEvents.UPDATE, f"remote.{ident}", {"state": state})

        # WAN sensors
        wan_stats = self.get_wan_stats()

        # WAN status sensor
        if wan_stats:
            status = wan_stats.get("status", "Unknown")
            wan_ip = wan_stats.get("wan_ip", "N/A")
            uptime = wan_stats.get("uptime", "")
            parts = [status]
            if wan_ip and wan_ip != "N/A":
                parts.append(wan_ip)
            if uptime:
                parts.append(uptime)
            status_value = " | ".join(parts)
        else:
            status_value = "No Gateway"
        self.events.emit(DeviceEvents.UPDATE, f"sensor.{ident}.wan1_status",
                        {"state": "ON", "value": status_value})

        # WAN download sensor
        dl_value = "N/A"
        if wan_stats:
            dl_value = self._format_speed(wan_stats.get("download_mbps", 0))
        self.events.emit(DeviceEvents.UPDATE, f"sensor.{ident}.wan1_download",
                        {"state": "ON", "value": dl_value})

        # WAN upload sensor
        ul_value = "N/A"
        if wan_stats:
            ul_value = self._format_speed(wan_stats.get("upload_mbps", 0))
        self.events.emit(DeviceEvents.UPDATE, f"sensor.{ident}.wan1_upload",
                        {"state": "ON", "value": ul_value})

        # Connected clients sensor
        self.events.emit(DeviceEvents.UPDATE, f"sensor.{ident}.connected_clients",
                        {"state": "ON", "value": str(self.client_count)})

        # PoE select entities - emit updated options
        poe_options = self._build_poe_options()
        if poe_options:
            self.events.emit(DeviceEvents.UPDATE, f"select.{ident}.poe_on",
                            {"state": "ON", "options": poe_options})
            self.events.emit(DeviceEvents.UPDATE, f"select.{ident}.poe_off",
                            {"state": "ON", "options": poe_options})

        _LOG.debug("[%s] Emitted entity updates (state=%s, sensors=%s, poe_opts=%d)",
                   self.log_id, state, "yes" if wan_stats else "no", len(poe_options))

    def _build_poe_options(self) -> list[str]:
        """Build PoE port option names from current device data."""
        options = []
        for dev_id, ports in self._ports.items():
            dev = self._network_devices.get(dev_id, {})
            dev_name = (dev.get("name") or dev.get("model") or dev_id)[:12]
            for port in ports:
                if not self._is_poe_port(port):
                    continue
                port_idx = port.get("port_idx", port.get("portIdx", port.get("idx", 0)))
                if port_idx == 0:
                    continue
                port_name = port.get("name")
                if port_name:
                    options.append(f"{dev_name} {port_name}")
                else:
                    options.append(f"{dev_name} P{port_idx}")
        return sorted(options)

    def _format_speed(self, mbps: float) -> str:
        """Format speed value for sensor display."""
        if mbps >= 1000:
            return f"{mbps/1000:.2f} Gbps"
        elif mbps >= 1:
            return f"{mbps:.1f} Mbps"
        elif mbps > 0:
            return f"{mbps*1000:.0f} Kbps"
        return "0 Mbps"

    def get_wan_stats(self, wan_index: int = 1) -> dict[str, Any] | None:
        """Get WAN statistics from gateway device."""
        if not self._gateway_device:
            return None

        dev = self._gateway_device

        wan_ip = dev.get("ipAddress")
        raw_state = dev.get("state", "")
        state = str(raw_state).upper() if raw_state else ""

        uplink = dev.get("uplink", {}) or {}
        wan = dev.get("wan1", dev.get("wan", {})) or {}
        if not wan_ip:
            wan_ip = uplink.get("ip") or wan.get("ip") or dev.get("wan_ip", "N/A")

        if state:
            is_up = state == "ONLINE" or state == "1"
        else:
            is_up = uplink.get("up", True)

        uptime = dev.get("uptime", 0)

        rx_rate = self._wan_health.get("rx_bytes-r", 0)
        tx_rate = self._wan_health.get("tx_bytes-r", 0)

        if not rx_rate and not tx_rate:
            rx_rate = (
                uplink.get("rx_bytes-r", 0) or
                uplink.get("rx_bytes_r", 0) or
                wan.get("rx_bytes-r", 0) or
                dev.get("rx_bytes-r", 0) or 0
            )
            tx_rate = (
                uplink.get("tx_bytes-r", 0) or
                uplink.get("tx_bytes_r", 0) or
                wan.get("tx_bytes-r", 0) or
                dev.get("tx_bytes-r", 0) or 0
            )

        download_mbps = (rx_rate * 8) / 1_000_000 if rx_rate else 0
        upload_mbps = (tx_rate * 8) / 1_000_000 if tx_rate else 0

        _LOG.debug("[%s] WAN stats: ip=%s, up=%s, rx=%d B/s (%.1f Mbps), tx=%d B/s (%.1f Mbps)",
                   self.log_id, wan_ip, is_up, rx_rate, download_mbps, tx_rate, upload_mbps)

        return {
            "status": "Connected" if is_up else "Disconnected",
            "wan_ip": wan_ip or "N/A",
            "download_mbps": download_mbps,
            "upload_mbps": upload_mbps,
            "uptime": self._format_uptime(uptime) if uptime else "",
        }

    def _format_uptime(self, seconds: int) -> str:
        """Format uptime to human readable."""
        days = seconds // 86400
        hours = (seconds % 86400) // 3600
        if days > 0:
            return f"{days}d {hours}h"
        return f"{hours}h {(seconds % 3600) // 60}m"

    # PoE port lookup for PoE select entities
    def find_port_for_option(self, option: str) -> tuple[str, int] | None:
        """Find device_id and port_idx for a PoE option name."""
        for dev_id, ports in self._ports.items():
            dev = self._network_devices.get(dev_id, {})
            dev_name = (dev.get("name") or dev.get("model") or dev_id)[:12]
            for port in ports:
                if not self._is_poe_port(port):
                    continue
                port_idx = port.get("port_idx", port.get("portIdx", port.get("idx", 0)))
                if port_idx == 0:
                    continue
                port_name = port.get("name")
                if port_name:
                    option_name = f"{dev_name} {port_name}"
                else:
                    option_name = f"{dev_name} P{port_idx}"
                if option_name == option:
                    return (dev_id, port_idx)
        return None

    # Protect camera methods
    async def set_camera_privacy(self, camera_id: str, enabled: bool) -> bool:
        return await self._api_patch(f"/proxy/protect/api/cameras/{camera_id}", {"privacyMode": enabled})

    async def set_camera_recording(self, camera_id: str, mode: str) -> bool:
        return await self._api_patch(f"/proxy/protect/api/cameras/{camera_id}", {"recordingSettings": {"mode": mode}})

    async def set_camera_ir_mode(self, camera_id: str, mode: str) -> bool:
        return await self._api_patch(f"/proxy/protect/api/cameras/{camera_id}", {"ispSettings": {"irLedMode": mode}})

    async def reboot_camera(self, camera_id: str) -> bool:
        return await self._api_post(f"/proxy/protect/api/cameras/{camera_id}/reboot")

    async def set_camera_floodlight(self, camera_id: str, enabled: bool, brightness: int = 255) -> bool:
        """Set camera floodlight on/off with optional brightness (0-255)."""
        data = {"ledSettings": {"isEnabled": enabled}}
        if enabled and brightness is not None:
            data["ledSettings"]["ledLevel"] = min(255, max(0, brightness))
        return await self._api_patch(f"/proxy/protect/api/cameras/{camera_id}", data)

    async def set_camera_quality(self, camera_id: str, quality: str) -> bool:
        """Set camera recording quality."""
        quality_map = {
            "4K": {"width": 3840, "height": 2160},
            "2K": {"width": 2560, "height": 1440},
            "1080p": {"width": 1920, "height": 1080},
            "720p": {"width": 1280, "height": 720},
            "480p": {"width": 854, "height": 480},
        }
        resolution = quality_map.get(quality, quality_map["1080p"])
        return await self._api_patch(
            f"/proxy/protect/api/cameras/{camera_id}",
            {"recordingSettings": {"videoResolution": resolution}}
        )

    async def take_camera_snapshot(self, camera_id: str) -> bool:
        """Request camera to take a snapshot."""
        return await self._api_post(f"/proxy/protect/api/cameras/{camera_id}/snapshot")

    async def restart_device(self, device_id: str) -> bool:
        """Restart a network device."""
        dev = self._network_devices.get(device_id, {})
        dev_name = dev.get("name", device_id)
        mac = dev.get("mac", device_id)

        _LOG.info("[%s] Restarting device %s (mac: %s)", self.log_id, dev_name, mac)

        if self._is_unifi_os:
            path = f"/proxy/network/api/s/{self._site_name}/cmd/devmgr"
        else:
            path = f"/api/s/{self._site_name}/cmd/devmgr"

        result = await self._api_post(path, {"cmd": "restart", "mac": mac})

        if not result and self._use_api_key:
            _LOG.warning(
                "[%s] Device restart failed - API key auth may not support device commands.",
                self.log_id
            )

        return result

    async def set_wlan_enabled(self, wlan_id: str, enabled: bool) -> bool:
        """Enable or disable a WLAN."""
        _LOG.info("[%s] Setting WLAN %s to %s", self.log_id, wlan_id, enabled)

        if self._is_unifi_os:
            path = f"/proxy/network/api/s/{self._site_name}/rest/wlanconf/{wlan_id}"
        else:
            path = f"/api/s/{self._site_name}/rest/wlanconf/{wlan_id}"

        result = await self._api_put(path, {"enabled": enabled})

        if not result and self._use_api_key:
            _LOG.warning(
                "[%s] WLAN control failed - API key auth may not support WLAN commands.",
                self.log_id
            )

        return result

    async def set_port_poe(self, device_id: str, port_idx: int, enabled: bool) -> bool:
        """Enable or disable PoE on a port."""
        mode = "auto" if enabled else "off"
        dev = self._network_devices.get(device_id, {})

        _LOG.info("[%s] Setting PoE %s on device %s port %d", self.log_id, mode, device_id, port_idx)

        dev_db_id = dev.get("_id", "")

        if not dev_db_id:
            _LOG.warning(
                "[%s] Device %s has no _id field. Trying Integration API path.",
                self.log_id, device_id
            )
            path = f"/proxy/network/integration/v1/sites/{self._site_id}/devices/{device_id}/ports/{port_idx}"
            return await self._api_put(path, {"poeMode": mode})

        port_overrides = list(dev.get("port_overrides", []))
        found = False
        for po in port_overrides:
            if isinstance(po, dict) and po.get("port_idx") == port_idx:
                po["poe_mode"] = mode
                found = True
                break
        if not found:
            port_overrides.append({"port_idx": port_idx, "poe_mode": mode})

        if self._is_unifi_os:
            path = f"/proxy/network/api/s/{self._site_name}/rest/device/{dev_db_id}"
        else:
            path = f"/api/s/{self._site_name}/rest/device/{dev_db_id}"

        return await self._api_put(path, {"port_overrides": port_overrides})
