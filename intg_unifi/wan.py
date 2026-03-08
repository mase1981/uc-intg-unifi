"""UniFi Network WAN sensors - Upload/Download speed per WAN.

:copyright: (c) 2026 by Meir Miyara.
:license: MPL-2.0
"""
import logging

from ucapi.sensor import Attributes, DeviceClasses, Sensor, States

from intg_unifi.config import UniFiConfig
from intg_unifi.device import UniFiDevice

_LOG = logging.getLogger(__name__)


class WANSpeedSensor(Sensor):
    """WAN speed sensor (upload or download)."""

    def __init__(
        self,
        device_config: UniFiConfig,
        device: UniFiDevice,
        direction: str,
        wan_index: int = 1,
    ):
        """Initialize WAN speed sensor."""
        self._device = device
        self._config = device_config
        self._direction = direction
        self._wan_index = wan_index

        direction_label = "Upload" if direction == "upload" else "Download"
        wan_label = f"WAN{wan_index}" if wan_index > 1 else "WAN"

        entity_id = f"sensor.{device_config.identifier}.wan{wan_index}_{direction}"

        initial_value = self._get_current_value()

        super().__init__(
            entity_id,
            f"{device_config.name} - {wan_label} {direction_label}",
            [],
            {
                Attributes.STATE: States.ON,
                Attributes.VALUE: initial_value,
            },
            device_class=DeviceClasses.CUSTOM,
            options={"custom_unit": "Mbps"},
        )

    def _get_current_value(self) -> str:
        """Get current throughput value from device (live data)."""
        stats = self._device.get_wan_stats(self._wan_index)
        if stats:
            if self._direction == "upload":
                mbps = stats.get("upload_mbps", 0)
            else:
                mbps = stats.get("download_mbps", 0)

            if mbps >= 1000:
                return f"{mbps/1000:.2f} Gbps"
            elif mbps >= 1:
                return f"{mbps:.1f} Mbps"
            elif mbps > 0:
                return f"{mbps*1000:.0f} Kbps"
            else:
                return "0 Mbps"
        return "N/A"

    def update_state(self):
        """Update WAN speed from device stats (called during poll)."""
        value = self._get_current_value()
        self.attributes[Attributes.VALUE] = value
        self.attributes[Attributes.STATE] = States.ON


class WANStatusSensor(Sensor):
    """WAN status sensor - connection state and IP."""

    def __init__(
        self,
        device_config: UniFiConfig,
        device: UniFiDevice,
        wan_index: int = 1,
    ):
        """Initialize WAN status sensor."""
        self._device = device
        self._config = device_config
        self._wan_index = wan_index

        wan_label = f"WAN{wan_index}" if wan_index > 1 else "WAN"
        entity_id = f"sensor.{device_config.identifier}.wan{wan_index}_status"

        initial_value = self._get_current_value()

        super().__init__(
            entity_id,
            f"{device_config.name} - {wan_label} Status",
            [],
            {
                Attributes.STATE: States.ON,
                Attributes.VALUE: initial_value,
            },
            device_class=DeviceClasses.CUSTOM,
        )

    def _get_current_value(self) -> str:
        """Get current status value from device."""
        stats = self._device.get_wan_stats(self._wan_index)
        if stats:
            status = stats.get("status", "Unknown")
            wan_ip = stats.get("wan_ip", "N/A")
            uptime = stats.get("uptime", "")

            if wan_ip and wan_ip != "N/A":
                if uptime:
                    return f"{status} | {wan_ip} | {uptime}"
                return f"{status} | {wan_ip}"
            return status
        return "No Gateway"

    def update_state(self):
        """Update WAN status from device stats (called during poll)."""
        value = self._get_current_value()
        self.attributes[Attributes.VALUE] = value
        self.attributes[Attributes.STATE] = States.ON


class ConnectedClientsSensor(Sensor):
    """Sensor showing number of connected clients."""

    def __init__(
        self,
        device_config: UniFiConfig,
        device: UniFiDevice,
    ):
        """Initialize connected clients sensor."""
        self._device = device
        self._config = device_config

        entity_id = f"sensor.{device_config.identifier}.connected_clients"
        initial_value = str(device.client_count)

        super().__init__(
            entity_id,
            f"{device_config.name} - Connected Clients",
            [],
            {
                Attributes.STATE: States.ON,
                Attributes.VALUE: initial_value,
            },
            device_class=DeviceClasses.CUSTOM,
        )

    def update_state(self):
        """Update client count from device (called during poll)."""
        self.attributes[Attributes.VALUE] = str(self._device.client_count)
        self.attributes[Attributes.STATE] = States.ON
