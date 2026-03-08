"""UniFi Remote entity - Control for WiFi networks and network devices.

:copyright: (c) 2026 by Meir Miyara.
:license: MPL-2.0
"""
import logging
from typing import Any

from ucapi import StatusCodes
from ucapi.remote import Attributes, Commands, Remote, States
from ucapi.ui import EntityCommand, Size, UiPage, create_ui_text

from intg_unifi.config import UniFiConfig
from intg_unifi.device import UniFiDevice

_LOG = logging.getLogger(__name__)


class UniFiRemote(Remote):
    """UniFi Remote entity with UI pages for WiFi and device control.

    UI pages are built at creation time from device data.
    Since require_connection_before_registry=True, the device is
    already connected with real data when this entity is created.
    """

    def __init__(self, device_config: UniFiConfig, device: UniFiDevice):
        """Initialize UniFi Remote."""
        self._device = device
        self._config = device_config

        ui_pages = self._build_ui_pages()
        simple_commands = self._build_simple_commands()

        super().__init__(
            f"remote.{device_config.identifier}",
            "UniFi Control",
            [],
            {Attributes.STATE: States.ON},
            simple_commands=simple_commands,
            cmd_handler=self._handle_command,
            ui_pages=ui_pages,
        )

        _LOG.info("[%s] Remote created with %d pages, %d commands",
                  device_config.name, len(ui_pages), len(simple_commands))

    def _build_simple_commands(self) -> list[str]:
        """Build list of all available commands."""
        commands = []

        for wlan_id in self._device.wlans.keys():
            commands.extend([
                f"wlan_on_{wlan_id}",
                f"wlan_off_{wlan_id}",
            ])

        for dev_id in self._device.network_devices.keys():
            commands.append(f"device_reboot_{dev_id}")

        return commands

    def _is_guest_wlan(self, wlan: dict) -> bool:
        """Check if WLAN is a guest network."""
        if wlan.get("is_guest"):
            return True
        if wlan.get("guest_mode_enabled"):
            return True
        if wlan.get("purpose") == "guest":
            return True
        name = (wlan.get("name") or wlan.get("ssid") or "").lower()
        if "guest" in name:
            return True
        return False

    async def _handle_command(
        self, entity: Remote, cmd_id: str, params: dict[str, Any] | None
    ) -> StatusCodes:
        """Handle remote commands."""
        if cmd_id == Commands.SEND_CMD:
            command = params.get("command", "") if params else ""
            success = await self._execute_command(command)
            return StatusCodes.OK if success else StatusCodes.SERVER_ERROR

        if cmd_id == Commands.SEND_CMD_SEQUENCE:
            sequence = params.get("sequence", []) if params else []
            for command in sequence:
                if not await self._execute_command(command):
                    return StatusCodes.SERVER_ERROR
            return StatusCodes.OK

        return StatusCodes.NOT_IMPLEMENTED

    async def _execute_command(self, command: str) -> bool:
        """Execute a single command."""
        _LOG.debug("[%s] Executing command: %s", self._config.name, command)

        if command.startswith("wlan_on_"):
            wlan_id = command.replace("wlan_on_", "")
            return await self._device.set_wlan_enabled(wlan_id, True)

        if command.startswith("wlan_off_"):
            wlan_id = command.replace("wlan_off_", "")
            return await self._device.set_wlan_enabled(wlan_id, False)

        if command.startswith("device_reboot_"):
            dev_id = command.replace("device_reboot_", "")
            return await self._device.restart_device(dev_id)

        _LOG.warning("[%s] Unknown command: %s", self._config.name, command)
        return False

    def _build_ui_pages(self) -> list[UiPage]:
        """Build UI pages from device data (available because connection happens first)."""
        pages = []

        wlans = self._device.wlans
        devices = self._device.network_devices

        if wlans:
            regular_wlans = {k: v for k, v in wlans.items() if not self._is_guest_wlan(v)}
            guest_wlans = {k: v for k, v in wlans.items() if self._is_guest_wlan(v)}

            if regular_wlans:
                pages.append(self._create_wifi_page(regular_wlans))

            if guest_wlans:
                pages.append(self._create_guest_page(guest_wlans))

        if devices:
            pages.append(self._create_devices_page(devices))

        if not pages:
            pages.append(UiPage(
                page_id="info",
                name="Info",
                items=[create_ui_text(text="UniFi Control", x=0, y=0, size=Size(width=4, height=1))],
            ))

        return pages

    def _create_wifi_page(self, wlans: dict) -> UiPage:
        """Create WiFi control page."""
        items = [
            create_ui_text(text="WiFi Networks", x=0, y=0, size=Size(width=4, height=1)),
        ]

        y = 1
        for wlan_id, wlan in wlans.items():
            wlan_name = (wlan.get("name") or wlan.get("ssid") or wlan_id)[:12]

            items.append(create_ui_text(text=wlan_name, x=0, y=y, size=Size(width=2, height=1)))
            items.append(create_ui_text(
                text="ON",
                x=2, y=y,
                cmd=EntityCommand(f"wlan_on_{wlan_id}", {"command": f"wlan_on_{wlan_id}"}),
            ))
            items.append(create_ui_text(
                text="OFF",
                x=3, y=y,
                cmd=EntityCommand(f"wlan_off_{wlan_id}", {"command": f"wlan_off_{wlan_id}"}),
            ))

            y += 1
            if y > 5:
                break

        return UiPage(page_id="wifi", name="WiFi", items=items)

    def _create_guest_page(self, guest_wlans: dict) -> UiPage:
        """Create Guest Networks control page."""
        items = [
            create_ui_text(text="Guest Networks", x=0, y=0, size=Size(width=4, height=1)),
        ]

        y = 1
        for wlan_id, wlan in guest_wlans.items():
            wlan_name = (wlan.get("name") or wlan.get("ssid") or wlan_id)[:12]

            items.append(create_ui_text(text=wlan_name, x=0, y=y, size=Size(width=2, height=1)))
            items.append(create_ui_text(
                text="ON",
                x=2, y=y,
                cmd=EntityCommand(f"wlan_on_{wlan_id}", {"command": f"wlan_on_{wlan_id}"}),
            ))
            items.append(create_ui_text(
                text="OFF",
                x=3, y=y,
                cmd=EntityCommand(f"wlan_off_{wlan_id}", {"command": f"wlan_off_{wlan_id}"}),
            ))

            y += 1
            if y > 5:
                break

        return UiPage(page_id="guest", name="Guest", items=items)

    def _create_devices_page(self, devices: dict) -> UiPage:
        """Create network devices page with reboot buttons."""
        items = [
            create_ui_text(text="Network Devices", x=0, y=0, size=Size(width=4, height=1)),
        ]

        y = 1
        for dev_id, dev in devices.items():
            dev_name = (dev.get("name") or dev.get("model") or "Unknown")[:12]

            items.append(create_ui_text(text=dev_name, x=0, y=y, size=Size(width=3, height=1)))
            items.append(create_ui_text(
                text="Reboot",
                x=3, y=y,
                cmd=EntityCommand(f"device_reboot_{dev_id}", {"command": f"device_reboot_{dev_id}"}),
            ))

            y += 1
            if y > 5:
                break

        return UiPage(page_id="devices", name="Devices", items=items)
