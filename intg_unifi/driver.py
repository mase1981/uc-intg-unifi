"""UniFi integration driver - Entity registration for UC Remote.

:copyright: (c) 2026 by Meir Miyara.
:license: MPL-2.0
"""
import logging

from ucapi_framework import BaseIntegrationDriver

from intg_unifi.camera import (
    ProtectCamera,
    ProtectCameraBinarySensor,
    ProtectCameraButton,
    ProtectCameraFloodlight,
    ProtectCameraIRModeSelect,
    ProtectCameraRecordingModeSelect,
    ProtectCameraSwitch,
)
from intg_unifi.config import UniFiConfig
from intg_unifi.device import UniFiDevice
from intg_unifi.poe import PoEOffSelect, PoEOnSelect
from intg_unifi.remote import UniFiRemote
from intg_unifi.wan import ConnectedClientsSensor, WANSpeedSensor, WANStatusSensor

_LOG = logging.getLogger(__name__)


def _has_floodlight(camera: dict) -> bool:
    """Check if camera has floodlight capability."""
    features = camera.get("featureFlags", {})
    return features.get("hasFloodlight", False) or features.get("hasLedSpot", False)


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

        if device.has_protect:
            for cam_id in device.cameras.keys():
                cam_entity_id = f"media_player.{cfg.identifier}.camera_{cam_id}"
                if not self.api.available_entities.contains(cam_entity_id):
                    self._add_and_configure_entity(ProtectCamera(cfg, device, cam_id))
                    self._add_and_configure_entity(ProtectCameraBinarySensor(cfg, device, cam_id, "motion"))
                    self._add_and_configure_entity(ProtectCameraSwitch(cfg, device, cam_id, "privacy"))
                    self._add_and_configure_entity(ProtectCameraRecordingModeSelect(cfg, device, cam_id))
                    self._add_and_configure_entity(ProtectCameraIRModeSelect(cfg, device, cam_id))
                    self._add_and_configure_entity(ProtectCameraButton(cfg, device, cam_id, "reboot"))
                    cam = device.cameras.get(cam_id, {})
                    if _has_floodlight(cam):
                        self._add_and_configure_entity(ProtectCameraFloodlight(cfg, device, cam_id))
            _LOG.info("[%s] Dynamically added %d camera entities", cfg.name, len(device.cameras))

    def on_device_removed(self, device_config) -> None:
        """Handle device removal."""
        if device_config is None:
            _LOG.info("Clearing all devices - disconnecting first")
            for device in list(self._device_instances.values()):
                self._loop.create_task(device.disconnect())
        else:
            device_id = self.get_device_id(device_config)
            device = self._device_instances.get(device_id)
            if device:
                _LOG.info("Removing device - disconnecting: %s", device_id)
                self._loop.create_task(device.disconnect())
        super().on_device_removed(device_config)
