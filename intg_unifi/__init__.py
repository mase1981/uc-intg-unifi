"""UniFi Network & Protect integration for Unfolded Circle Remote.

:copyright: (c) 2026 by Meir Miyara.
:license: MPL-2.0
"""
import asyncio
import json
import logging
import os
from pathlib import Path

from ucapi import DeviceStates
from ucapi_framework import BaseConfigManager, get_config_path

from intg_unifi.config import UniFiConfig
from intg_unifi.driver import UniFiDriver
from intg_unifi.setup_flow import UniFiSetupFlow

try:
    driver_path = Path(__file__).parent.parent / "driver.json"
    with open(driver_path, "r", encoding="utf-8") as f:
        __version__ = json.load(f).get("version", "0.0.0")
except (FileNotFoundError, json.JSONDecodeError):
    __version__ = "0.0.0"

_LOG = logging.getLogger(__name__)


async def main():
    """Start the UniFi integration."""
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s",
    )
    logging.getLogger("ucapi_framework").setLevel(logging.DEBUG)
    logging.getLogger("ucapi").setLevel(logging.DEBUG)
    logging.getLogger("intg_unifi").setLevel(logging.DEBUG)
    _LOG.info("Starting UniFi Integration v%s", __version__)

    driver = UniFiDriver()
    config_path = get_config_path(driver.api.config_dir_path or "")
    config_manager = BaseConfigManager(
        config_path,
        add_handler=driver.on_device_added,
        remove_handler=driver.on_device_removed,
        config_class=UniFiConfig,
    )
    driver.config_manager = config_manager

    setup_handler = UniFiSetupFlow.create_handler(driver)
    driver_path = os.path.join(os.path.dirname(__file__), "..", "driver.json")
    await driver.api.init(os.path.abspath(driver_path), setup_handler)
    await driver.register_all_configured_devices(connect=False)

    device_count = len(list(config_manager.all()))
    if device_count > 0:
        await driver.api.set_device_state(DeviceStates.CONNECTED)
    else:
        await driver.api.set_device_state(DeviceStates.DISCONNECTED)

    _LOG.info("UniFi Integration started")
    await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
