"""UniFi Network PoE select entities - Single selects for all PoE ports.

:copyright: (c) 2026 by Meir Miyara.
:license: MPL-2.0
"""
import logging
from typing import Any

from ucapi import StatusCodes
from ucapi.select import Attributes, Select, States

from intg_unifi.config import UniFiConfig
from intg_unifi.device import UniFiDevice

_LOG = logging.getLogger(__name__)


def _is_poe_port(port: dict) -> bool:
    """Check if port has PoE capability."""
    poe = port.get("poe")
    if isinstance(poe, dict):
        return poe.get("enabled", False) or poe.get("state") == "UP"
    if port.get("port_poe", False):
        return True
    if poe:
        return True
    if port.get("poeEnabled", False):
        return True
    poe_mode = port.get("poeMode", port.get("poe_mode", ""))
    if poe_mode and poe_mode != "off":
        return True
    if port.get("poe_caps", 0) > 0:
        return True
    port_caps = port.get("portCaps", port.get("port_caps", 0))
    if isinstance(port_caps, int) and port_caps & 0x08:
        return True
    return False


def _get_port_idx(port: dict) -> int:
    """Get port index from port data."""
    return port.get("port_idx", port.get("portIdx", port.get("idx", 0)))


def _build_options(device: UniFiDevice) -> list[str]:
    """Build list of PoE port option names from device data."""
    options = []
    for dev_id, ports in device.ports.items():
        dev = device.network_devices.get(dev_id, {})
        dev_name = (dev.get("name") or dev.get("model") or dev_id)[:12]

        for port in ports:
            if not _is_poe_port(port):
                continue
            port_idx = _get_port_idx(port)
            if port_idx == 0:
                continue
            port_name = port.get("name")
            if port_name:
                options.append(f"{dev_name} {port_name}")
            else:
                options.append(f"{dev_name} P{port_idx}")

    return sorted(options)


class PoEOnSelect(Select):
    """Select to turn ON PoE for any port."""

    def __init__(self, device_config: UniFiConfig, device: UniFiDevice):
        """Initialize PoE On select."""
        self._device = device
        self._config = device_config

        options = _build_options(device)
        entity_id = f"select.{device_config.identifier}.poe_on"

        _LOG.info("[%s] PoE On select: %d ports", device_config.name, len(options))

        super().__init__(
            entity_id,
            f"{device_config.name} - PoE On",
            {
                Attributes.STATE: States.ON,
                Attributes.OPTIONS: options,
            },
            cmd_handler=self.handle_command,
        )

    async def handle_command(
        self, entity: Select, cmd_id: str, params: dict[str, Any] | None
    ) -> StatusCodes:
        """Handle select command - turn on PoE for selected port."""
        if cmd_id == "select_option" and params and "option" in params:
            option = params["option"]
            port_info = self._device.find_port_for_option(option)
            if port_info:
                dev_id, port_idx = port_info
                success = await self._device.set_port_poe(dev_id, port_idx, True)
                if success:
                    _LOG.info("[%s] PoE enabled on %s", self._config.name, option)
                    return StatusCodes.OK
                return StatusCodes.SERVER_ERROR
            _LOG.warning("[%s] PoE port not found: %s", self._config.name, option)
            return StatusCodes.BAD_REQUEST
        return StatusCodes.NOT_IMPLEMENTED


class PoEOffSelect(Select):
    """Select to turn OFF PoE for any port."""

    def __init__(self, device_config: UniFiConfig, device: UniFiDevice):
        """Initialize PoE Off select."""
        self._device = device
        self._config = device_config

        options = _build_options(device)
        entity_id = f"select.{device_config.identifier}.poe_off"

        _LOG.info("[%s] PoE Off select: %d ports", device_config.name, len(options))

        super().__init__(
            entity_id,
            f"{device_config.name} - PoE Off",
            {
                Attributes.STATE: States.ON,
                Attributes.OPTIONS: options,
            },
            cmd_handler=self.handle_command,
        )

    async def handle_command(
        self, entity: Select, cmd_id: str, params: dict[str, Any] | None
    ) -> StatusCodes:
        """Handle select command - turn off PoE for selected port."""
        if cmd_id == "select_option" and params and "option" in params:
            option = params["option"]
            port_info = self._device.find_port_for_option(option)
            if port_info:
                dev_id, port_idx = port_info
                success = await self._device.set_port_poe(dev_id, port_idx, False)
                if success:
                    _LOG.info("[%s] PoE disabled on %s", self._config.name, option)
                    return StatusCodes.OK
                return StatusCodes.SERVER_ERROR
            _LOG.warning("[%s] PoE port not found: %s", self._config.name, option)
            return StatusCodes.BAD_REQUEST
        return StatusCodes.NOT_IMPLEMENTED
