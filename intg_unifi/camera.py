"""UniFi Protect camera entities - ALL camera-related entity types.

:copyright: (c) 2026 by Meir Miyara.
:license: MPL-2.0
"""
import logging
from typing import Any

from ucapi import StatusCodes
from ucapi.button import Attributes as ButtonAttributes, Button, Commands as ButtonCommands
from ucapi.light import Attributes as LightAttributes, Commands as LightCommands, Features as LightFeatures, Light, States as LightStates
from ucapi.media_player import Attributes as MediaAttributes, DeviceClasses as MediaClasses, MediaPlayer, States as MediaStates
from ucapi.select import Attributes as SelectAttributes, Select, States as SelectStates
from ucapi.sensor import Attributes as SensorAttributes, DeviceClasses as SensorClasses, Sensor, States as SensorStates
from ucapi.switch import Attributes as SwitchAttributes, DeviceClasses as SwitchClasses, States as SwitchStates, Switch

from intg_unifi.config import UniFiConfig
from intg_unifi.device import UniFiDevice

_LOG = logging.getLogger(__name__)


def _get_camera_name(camera: dict | None, camera_id: str) -> str:
    """Get camera name from API dict."""
    if not camera:
        return f"Camera {camera_id}"
    return camera.get("name") or camera.get("displayName") or f"Camera {camera_id}"


class ProtectCamera(MediaPlayer):
    """Camera snapshot display via media_player (UC Remote has no video entity)."""

    def __init__(self, device_config: UniFiConfig, device: UniFiDevice, camera_id: str):
        """Initialize camera media player."""
        self._device = device
        self._camera_id = camera_id
        camera = device.cameras.get(camera_id)
        camera_name = _get_camera_name(camera, camera_id)
        entity_id = f"media_player.{device_config.identifier}_camera_{camera_id}"

        is_connected = camera.get("isConnected", False) if camera else False
        super().__init__(
            entity_id,
            f"{device_config.name} - {camera_name}",
            [],
            {
                MediaAttributes.STATE: MediaStates.ON if is_connected else MediaStates.OFF,
                MediaAttributes.MEDIA_IMAGE_URL: "",
            },
            device_class=MediaClasses.STREAMING,
            cmd_handler=self.handle_command,
        )

    async def handle_command(self, entity: MediaPlayer, cmd_id: str, params: dict[str, Any] | None) -> StatusCodes:
        """Handle commands (none supported for snapshot display)."""
        return StatusCodes.NOT_IMPLEMENTED


class ProtectCameraBinarySensor(Sensor):
    """Camera binary sensors (motion, doorbell, recording) - uses Sensor with BINARY device class."""

    SENSOR_TYPES = {
        "motion": ("Motion", "motion", "is_motion_detected"),
        "doorbell": ("Doorbell", "doorbell", "is_ringing"),
        "recording": ("Recording", "recording", "is_recording"),
    }

    def __init__(self, device_config: UniFiConfig, device: UniFiDevice, camera_id: str, sensor_type: str):
        """Initialize camera binary sensor."""
        self._device = device
        self._camera_id = camera_id
        self._sensor_type = sensor_type

        if sensor_type not in self.SENSOR_TYPES:
            raise ValueError(f"Invalid sensor type: {sensor_type}")

        name_suffix, unit_label, self._attr_name = self.SENSOR_TYPES[sensor_type]
        camera = device.cameras.get(camera_id)
        camera_name = _get_camera_name(camera, camera_id)
        entity_id = f"sensor.{device_config.identifier}_{sensor_type}_{camera_id}"

        super().__init__(
            entity_id,
            f"{device_config.name} - {camera_name} {name_suffix}",
            [],
            {SensorAttributes.STATE: SensorStates.UNAVAILABLE, SensorAttributes.VALUE: "off"},
            device_class=SensorClasses.BINARY,
            options={"custom_unit": unit_label},
        )

    def update_state(self):
        """Update binary sensor state from camera."""
        camera = self._device.cameras.get(self._camera_id)
        if camera:
            is_active = camera.get(self._attr_name, False)
            self.attributes[SensorAttributes.STATE] = SensorStates.ON
            self.attributes[SensorAttributes.VALUE] = "on" if is_active else "off"


class ProtectCameraSwitch(Switch):
    """Camera switches (privacy, status light, HDR, high FPS)."""

    SWITCH_TYPES = {
        "privacy": ("Privacy Mode", "privacyMode"),
        "status_light": ("Status Light", "ledSettings.isEnabled"),
        "hdr": ("HDR Mode", "hdrMode"),
        "high_fps": ("High FPS Mode", "videoMode"),
    }

    def __init__(self, device_config: UniFiConfig, device: UniFiDevice, camera_id: str, switch_type: str):
        """Initialize camera switch."""
        self._device = device
        self._camera_id = camera_id
        self._switch_type = switch_type

        if switch_type not in self.SWITCH_TYPES:
            raise ValueError(f"Invalid switch type: {switch_type}")

        name_suffix, self._state_path = self.SWITCH_TYPES[switch_type]
        camera = device.cameras.get(camera_id)
        camera_name = _get_camera_name(camera, camera_id)
        entity_id = f"switch.{device_config.identifier}_{switch_type}_{camera_id}"

        super().__init__(
            entity_id,
            f"{device_config.name} - {camera_name} {name_suffix}",
            [],
            {SwitchAttributes.STATE: SwitchStates.UNAVAILABLE},
            device_class=SwitchClasses.SWITCH,
            cmd_handler=self.handle_command,
        )

    async def handle_command(self, entity: Switch, cmd_id: str, params: dict[str, Any] | None) -> StatusCodes:
        """Handle switch commands."""
        if cmd_id == "toggle":
            current_state = self.attributes.get(SwitchAttributes.STATE) == SwitchStates.ON
            method = getattr(self._device, f"set_camera_{self._switch_type}")
            success = await method(self._camera_id, not current_state)
            if success:
                self.attributes[SwitchAttributes.STATE] = SwitchStates.OFF if current_state else SwitchStates.ON
                return StatusCodes.OK
            return StatusCodes.SERVER_ERROR
        return StatusCodes.NOT_IMPLEMENTED

    def update_state(self):
        """Update switch state from camera."""
        camera = self._device.cameras.get(self._camera_id)
        if not camera:
            return
        if self._switch_type == "privacy":
            is_on = camera.get("privacyMode", False)
        elif self._switch_type == "status_light":
            led = camera.get("ledSettings", {})
            is_on = led.get("isEnabled", False)
        elif self._switch_type == "hdr":
            is_on = camera.get("hdrMode", False)
        elif self._switch_type == "high_fps":
            is_on = camera.get("videoMode") == "highFps"
        else:
            is_on = False
        self.attributes[SwitchAttributes.STATE] = SwitchStates.ON if is_on else SwitchStates.OFF


class ProtectCameraRecordingModeSelect(Select):
    """Camera recording mode select."""

    RECORDING_MODES = ["always", "motion", "never", "detections"]

    def __init__(self, device_config: UniFiConfig, device: UniFiDevice, camera_id: str):
        """Initialize recording mode select."""
        self._device = device
        self._camera_id = camera_id
        camera = device.cameras.get(camera_id)
        camera_name = _get_camera_name(camera, camera_id)
        entity_id = f"select.{device_config.identifier}_recording_mode_{camera_id}"

        rec_settings = camera.get("recordingSettings", {}) if camera else {}
        current_mode = rec_settings.get("mode", "motion")

        super().__init__(
            entity_id,
            f"{device_config.name} - {camera_name} Recording Mode",
            {
                SelectAttributes.STATE: SelectStates.ON if camera else SelectStates.UNAVAILABLE,
                SelectAttributes.VALUE: current_mode,
                SelectAttributes.OPTIONS: self.RECORDING_MODES,
            },
            cmd_handler=self.handle_command,
        )

    async def handle_command(self, entity: Select, cmd_id: str, params: dict[str, Any] | None) -> StatusCodes:
        """Handle select commands."""
        if cmd_id == "select_option" and params and "option" in params:
            mode = params["option"]
            if mode in self.RECORDING_MODES:
                success = await self._device.set_camera_recording(self._camera_id, mode)
                if success:
                    self.attributes[SelectAttributes.VALUE] = mode
                    self.attributes[SelectAttributes.STATE] = SelectStates.ON
                    return StatusCodes.OK
            return StatusCodes.BAD_REQUEST
        return StatusCodes.NOT_IMPLEMENTED


class ProtectCameraIRModeSelect(Select):
    """Camera IR mode select."""

    IR_MODES = ["auto", "on", "off", "autoFilterOnly"]

    def __init__(self, device_config: UniFiConfig, device: UniFiDevice, camera_id: str):
        """Initialize IR mode select."""
        self._device = device
        self._camera_id = camera_id
        camera = device.cameras.get(camera_id)
        camera_name = _get_camera_name(camera, camera_id)
        entity_id = f"select.{device_config.identifier}_ir_mode_{camera_id}"

        isp_settings = camera.get("ispSettings", {}) if camera else {}
        current_mode = isp_settings.get("irLedMode", "auto")

        super().__init__(
            entity_id,
            f"{device_config.name} - {camera_name} IR Mode",
            {
                SelectAttributes.STATE: SelectStates.ON if camera else SelectStates.UNAVAILABLE,
                SelectAttributes.VALUE: current_mode,
                SelectAttributes.OPTIONS: self.IR_MODES,
            },
            cmd_handler=self.handle_command,
        )

    async def handle_command(self, entity: Select, cmd_id: str, params: dict[str, Any] | None) -> StatusCodes:
        """Handle select commands."""
        if cmd_id == "select_option" and params and "option" in params:
            mode = params["option"]
            if mode in self.IR_MODES:
                success = await self._device.set_camera_ir_mode(self._camera_id, mode)
                if success:
                    self.attributes[SelectAttributes.VALUE] = mode
                    self.attributes[SelectAttributes.STATE] = SelectStates.ON
                    return StatusCodes.OK
            return StatusCodes.BAD_REQUEST
        return StatusCodes.NOT_IMPLEMENTED


class ProtectCameraButton(Button):
    """Camera buttons (reboot, snapshot)."""

    BUTTON_TYPES = {
        "reboot": "Reboot Camera",
        "snapshot": "Take Snapshot",
    }

    def __init__(self, device_config: UniFiConfig, device: UniFiDevice, camera_id: str, button_type: str):
        """Initialize camera button."""
        self._device = device
        self._camera_id = camera_id
        self._button_type = button_type

        if button_type not in self.BUTTON_TYPES:
            raise ValueError(f"Invalid button type: {button_type}")

        camera = device.cameras.get(camera_id)
        camera_name = _get_camera_name(camera, camera_id)
        entity_id = f"button.{device_config.identifier}_{button_type}_{camera_id}"

        super().__init__(
            entity_id,
            f"{device_config.name} - {camera_name} {self.BUTTON_TYPES[button_type]}",
            cmd_handler=self.handle_command,
        )

    async def handle_command(self, entity: Button, cmd_id: str, params: dict[str, Any] | None) -> StatusCodes:
        """Handle button commands."""
        if cmd_id == ButtonCommands.PUSH:
            if self._button_type == "reboot":
                success = await self._device.reboot_camera(self._camera_id)
            elif self._button_type == "snapshot":
                success = await self._device.take_camera_snapshot(self._camera_id)
            else:
                return StatusCodes.NOT_IMPLEMENTED

            return StatusCodes.OK if success else StatusCodes.SERVER_ERROR
        return StatusCodes.NOT_IMPLEMENTED


class ProtectCameraFloodlight(Light):
    """Camera floodlight control (for cameras with floodlights)."""

    def __init__(self, device_config: UniFiConfig, device: UniFiDevice, camera_id: str):
        """Initialize floodlight."""
        self._device = device
        self._camera_id = camera_id
        camera = device.cameras.get(camera_id)
        camera_name = _get_camera_name(camera, camera_id)
        entity_id = f"light.{device_config.identifier}_floodlight_{camera_id}"

        led_settings = camera.get("ledSettings", {}) if camera else {}
        is_enabled = led_settings.get("isEnabled", False)
        brightness = led_settings.get("ledLevel", 255)

        super().__init__(
            entity_id,
            f"{device_config.name} - {camera_name} Floodlight",
            [LightFeatures.ON_OFF, LightFeatures.DIM],
            {
                LightAttributes.STATE: LightStates.ON if is_enabled else LightStates.OFF,
                LightAttributes.BRIGHTNESS: brightness,
            },
            cmd_handler=self.handle_command,
        )

    async def handle_command(self, entity: Light, cmd_id: str, params: dict[str, Any] | None) -> StatusCodes:
        """Handle light commands."""
        if cmd_id == LightCommands.ON:
            brightness = params.get("brightness", 255) if params else 255
            success = await self._device.set_camera_floodlight(self._camera_id, True, brightness)
            if success:
                self.attributes[LightAttributes.STATE] = LightStates.ON
                self.attributes[LightAttributes.BRIGHTNESS] = brightness
                return StatusCodes.OK
            return StatusCodes.SERVER_ERROR
        elif cmd_id == LightCommands.OFF:
            success = await self._device.set_camera_floodlight(self._camera_id, False, 0)
            if success:
                self.attributes[LightAttributes.STATE] = LightStates.OFF
                return StatusCodes.OK
            return StatusCodes.SERVER_ERROR
        return StatusCodes.NOT_IMPLEMENTED
