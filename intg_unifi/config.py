"""UniFi integration configuration - supports API key and username/password."""
from dataclasses import dataclass


@dataclass
class UniFiConfig:
    """UniFi device configuration."""

    identifier: str
    name: str
    host: str

    # Authentication - either API key OR username/password
    api_key: str = ""
    username: str = ""
    password: str = ""

    verify_ssl: bool = False
