"""Addon options."""
from typing import Dict, List

import attr


SS_TOPIC = "PYLONTECH/status"


@attr.define(slots=True)
class Options:
    """HASS Addon Options."""

    # pylint: disable=too-few-public-methods
    mqtt_host: str = ""
    mqtt_port: int = 0
    mqtt_username: str = ""
    mqtt_password: str = ""
    pylontech_id: str = ""
    pylontech_serial: str = ""
    sensor_prefix: str = "pylontech_"
    timeout: int = 10
    debug: int = 1
    port: str = ""
    host: str = ""
    max_batt: int = 0

    def update(self, json: Dict) -> None:
        """Update options."""
        for key, val in json.items():
            setattr(self, key.lower(), val)


OPT = Options()
