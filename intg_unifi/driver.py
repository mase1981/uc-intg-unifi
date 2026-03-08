"""UniFi integration driver - Entity registration for UC Remote.

:copyright: (c) 2026 by Meir Miyara.
:license: MPL-2.0
"""
import logging

from ucapi_framework import BaseIntegrationDriver

from intg_unifi.camera import ProtectCameraMediaPlayer, ProtectCameraSelect
from intg_unifi.config import UniFiConfig
from intg_unifi.device import UniFiDevice
from intg_unifi.poe import PoEOffSelect, PoEOnSelect
from intg_unifi.remote import UniFiRemote
from intg_unifi.wan import ConnectedClientsSensor, WANSpeedSensor, WANStatusSensor

_LOG = logging.getLogger(__name__)


class UniFiDriver(BaseIntegrationDriver[UniFiDevice, UniFiConfig]):
    """UniFi integration driver.

    Hybrid entity registration:
    - Static entities (sensors, selects) created immediately for reboot survival
    - Remote entity added dynamically after device connects (UI pages need real data)
    - Camera entities added dynamically after Protect discovery
    """

    def __init__(self):
        """Initialize UniFi driver."""
        super().__init__(
            device_class=UniFiDevice,
            entity_classes=[
                # Remote: SKIP here, added dynamically in on_device_connected
                # (UI pages are immutable after registration, need real WLAN/device data)

                lambda cfg, dev: [WANStatusSensor(cfg, dev, wan_index=1)],
                lambda cfg, dev: [WANSpeedSensor(cfg, dev, "download", wan_index=1)],
                lambda cfg, dev: [WANSpeedSensor(cfg, dev, "upload", wan_index=1)],
                lambda cfg, dev: [ConnectedClientsSensor(cfg, dev)],

                lambda cfg, dev: [PoEOnSelect(cfg, dev)],
                lambda cfg, dev: [PoEOffSelect(cfg, dev)],
            ],
            driver_id="unifi",
        )
        self._camera_media_players: dict[str, ProtectCameraMediaPlayer] = {}
        _LOG.info("UniFi driver initialized")

    def _add_and_configure_entity(self, entity) -> None:
        """Add entity to both available and configured entities.

        After reboot, Remote sends subscribe_events before dynamic entities exist.
        Those entities miss the subscription window. Adding to configured_entities
        ensures they appear in entity_states responses.
        """
        self.add_entity(entity)
        if not self.api.configured_entities.contains(entity.id):
            self.api.configured_entities.add(entity)

    async def on_device_connected(self, device_id: str) -> None:
        """Handle device connection - dynamically add remote and camera entities."""
        await super().on_device_connected(device_id)

        device = self._device_instances.get(device_id)
        if not device:
            return

        cfg = device.device_config
        remote_id = f"remote.{cfg.identifier}"

        if not self.api.available_entities.contains(remote_id):
            remote = UniFiRemote(cfg, device)
            self._add_and_configure_entity(remote)
            _LOG.info("[%s] Dynamically added remote entity with UI pages", cfg.name)

        if device.has_protect and device.cameras:
            mp_id = f"media_player.{cfg.identifier}.protect_cameras"
            if not self.api.available_entities.contains(mp_id):
                mp = ProtectCameraMediaPlayer(cfg, device)
                mp.set_api(self.api)

                select = ProtectCameraSelect(cfg, device, mp)
                select.set_api(self.api)

                mp.set_select_entity(select)

                self._add_and_configure_entity(mp)
                self._add_and_configure_entity(select)
                self._camera_media_players[device_id] = mp

                _LOG.info("[%s] Dynamically added Protect camera entities (%d cameras)", cfg.name, len(device.cameras))

    def on_device_removed(self, device_config) -> None:
        """Handle device removal."""
        if device_config is None:
            _LOG.info("Clearing all devices - disconnecting first")
            for device in list(self._device_instances.values()):
                self._loop.create_task(device.disconnect())
            for mp in self._camera_media_players.values():
                self._loop.create_task(mp.disconnect())
            self._camera_media_players.clear()
        else:
            device_id = self.get_device_id(device_config)
            device = self._device_instances.get(device_id)
            if device:
                _LOG.info("Removing device - disconnecting: %s", device_id)
                self._loop.create_task(device.disconnect())
            mp = self._camera_media_players.pop(device_id, None)
            if mp:
                self._loop.create_task(mp.disconnect())
        super().on_device_removed(device_config)
