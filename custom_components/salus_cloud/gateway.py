"""Values a gateway reports in its own shadow: Wi-Fi gateways (e.g. SAWZ600GW) and receivers switching a boiler.

Patterns match the full property name; the endpoint differs per gateway model.
"""

from __future__ import annotations

import re
from typing import Any

from .shadow import as_int

FIRMWARE_PATTERN = re.compile(r"^ep\d+:(?:sZDO:FirmwareVersion|sGateway:GatewaySoftwareVersion)$")
HARDWARE_PATTERN = re.compile(r"^ep\d+:sGateway:GatewayHardwareVersion$")
# Wi-Fi signal strength in dBm
RSSI_PATTERN = re.compile(r"^ep\d+:sGateway:WiFiRSSI$")
# Connection to Salus Cloud (1 connected)
CLOUD_PATTERN = re.compile(r"^ep\d+:sAWSIoT:CloudStatus$")
# Boiler relay of a receiver (1 on)
RELAY_PATTERN = re.compile(r"^ep\d+:sComm:RelayStatus$")
# Receiver mode: bit 1 set = switched by hand on the receiver, bit 0 set = relay off
PANEL_SWITCH_PATTERN = re.compile(r"^ep\d+:sComm:PanelSwitchStatus$")
RECEIVER_MODE_OPTIONS = ["auto", "manual_on", "manual_off"]


def receiver_mode(raw: Any) -> str | None:
    """Return auto / manual_on / manual_off from PanelSwitchStatus."""
    if (value := as_int(raw)) is None:
        return None
    if not value & 0b10:
        return "auto"
    return "manual_off" if value & 0b01 else "manual_on"
