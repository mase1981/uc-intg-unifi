"""UniFi setup flow - username/password authentication.

:copyright: (c) 2026 by Meir Miyara.
:license: MPL-2.0
"""
import asyncio
import logging
from typing import Any

from ucapi import RequestUserInput
from ucapi_framework import BaseSetupFlow

from intg_unifi.config import UniFiConfig
from intg_unifi.device import UniFiDevice

_LOG = logging.getLogger(__name__)


class UniFiSetupFlow(BaseSetupFlow[UniFiConfig]):
    """UniFi Console setup flow."""

    def get_manual_entry_form(self) -> RequestUserInput:
        """Get manual entry form for setup."""
        return RequestUserInput(
            {"en": "UniFi Console Setup"},
            [
                {
                    "id": "name",
                    "label": {"en": "Device Name"},
                    "field": {"text": {"value": "UniFi"}},
                },
                {
                    "id": "host",
                    "label": {"en": "UniFi Console IP Address"},
                    "field": {"text": {"value": ""}},
                },
                {
                    "id": "username",
                    "label": {"en": "Username (local account only)"},
                    "field": {"text": {"value": ""}},
                },
                {
                    "id": "password",
                    "label": {"en": "Password"},
                    "field": {"password": {"value": ""}},
                },
                {
                    "id": "verify_ssl",
                    "label": {"en": "Verify SSL Certificate"},
                    "field": {"checkbox": {"value": False}},
                },
            ],
        )

    async def query_device(
        self, input_values: dict[str, Any]
    ) -> UniFiConfig | RequestUserInput:
        """Validate connection and create configuration.

        Keep lightweight - only authenticate, defer heavy data loading to device.connect().
        """
        _LOG.info("query_device called with: %s", list(input_values.keys()))

        host = input_values.get("host", "").strip()
        if not host:
            raise ValueError("IP address is required")

        username = input_values.get("username", "").strip()
        password = input_values.get("password", "").strip()

        if not username or not password:
            raise ValueError("Username and Password are required")

        verify_ssl = input_values.get("verify_ssl", False)
        if isinstance(verify_ssl, str):
            verify_ssl = verify_ssl.lower() == "true"

        config = UniFiConfig(
            identifier=f"unifi_{host.replace('.', '_')}",
            name=input_values.get("name", "UniFi").strip() or "UniFi",
            host=host,
            api_key="",
            username=username,
            password=password,
            verify_ssl=verify_ssl,
        )

        _LOG.info("Testing connection to UniFi Console at %s", host)
        device = UniFiDevice(config)
        try:
            async with asyncio.timeout(30):
                await device.connect()
            _LOG.info("Successfully connected to UniFi Console")
            _LOG.info("Devices: %d, WLANs: %d, Clients: %d",
                     len(device.network_devices), len(device.wlans), len(device.clients))
            await device.disconnect()
            _LOG.info("Validation device disconnected")
            return config
        except Exception as err:
            _LOG.error("Connection test failed: %s", err)
            raise ConnectionError(f"Failed to connect: {err}") from err
