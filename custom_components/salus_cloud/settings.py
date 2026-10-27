"""Thermostat settings and gateway (receiver) values the Salus app shows, as found in its iT800 device model.

Settings are written through the matching Set* shadow property with the values the Salus app sends. They are
limited to the iT800 family (ep1 properties): iT600 (ep9) devices use other value encodings for the same names.
An entity is only created when the device reports the property.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# Thermostat settings in the Salus app: Settings and Advanced settings of an IT800TX


@dataclass(frozen=True, kw_only=True)
class SwitchSetting:
    """On/off setting."""

    key: str
    pattern: re.Pattern[str]
    on_value: int = 1
    off_value: int = 0
    config: bool = True


SWITCH_SETTINGS: tuple[SwitchSetting, ...] = (
    # Lock icon on the device page of the Salus app (1 locked, 0 unlocked)
    SwitchSetting(key="key_lock", pattern=re.compile(r"^ep1:sTherUIS:LockKey$"), config=False),
    SwitchSetting(key="display_always_on", pattern=re.compile(r"^ep1:sComm:DisplayAlwaysOn$")),
    SwitchSetting(key="optimum_start", pattern=re.compile(r"^ep1:sComm:OptimizeStart$")),
    SwitchSetting(key="optimum_stop", pattern=re.compile(r"^ep1:sComm:OptimizeStop$")),
    # The app's "Frost protection" setting writes HolidayActive
    SwitchSetting(key="frost_protection", pattern=re.compile(r"^ep1:sComm:HolidayActive$")),
)


@dataclass(frozen=True, kw_only=True)
class SelectSetting:
    """Setting with a fixed list of values; options are translation keys."""

    key: str
    pattern: re.Pattern[str]
    options: dict[int, str]


SELECT_SETTINGS: tuple[SelectSetting, ...] = (
    SelectSetting(
        key="display_brightness",
        pattern=re.compile(r"^ep1:sComm:LEDBrightness$"),
        options={204: "high", 64: "low"},
    ),
    SelectSetting(
        key="temperature_display_resolution",
        pattern=re.compile(r"^ep1:sComm:TempDisplayResolution$"),
        options={5: "half_degree", 1: "tenth_degree"},
    ),
    SelectSetting(
        key="heating_control",
        pattern=re.compile(r"^ep1:sComm:HeatingControlAlgorithm$"),
        options={
            0: "hysteresis_0_25",
            1: "hysteresis_0_5",
            3: "hysteresis_1_0",
            4: "hysteresis_1_5",
            5: "hysteresis_2_0",
            16: "tpi_underfloor",
            17: "tpi_radiator",
            18: "tpi_electric",
        },
    ),
)


def find_key(properties: dict[str, Any], pattern: re.Pattern[str]) -> str | None:
    """Return the first reported property (sorted) whose full name matches the pattern."""
    return next((key for key in sorted(properties) if pattern.search(key)), None)


# Temperature calibration is reported as an unsigned byte (-0.5 °C comes back as 251) but written signed (-5)
def signed_byte(raw: Any) -> Any:
    """Return a value reported as an unsigned byte as the signed value it stands for."""
    if isinstance(raw, int) and not isinstance(raw, bool) and 127 < raw < 256:
        return raw - 256
    return raw


# Gateway / Wi-Fi receiver (e.g. the IT800 receiver that switches the boiler)

# Boiler relay of the receiver (1 on)
GATEWAY_RELAY_PATTERN = re.compile(r"^ep\d+:sComm:RelayStatus$")
# Receiver mode as the app decodes it: bit 1 set = manual (on the receiver's switch), bit 0 set = relay off
GATEWAY_PANEL_SWITCH_PATTERN = re.compile(r"^ep\d+:sComm:PanelSwitchStatus$")
RECEIVER_MODE_OPTIONS = ["auto", "manual_on", "manual_off"]


def receiver_mode(raw: Any) -> str | None:
    """Return auto / manual_on / manual_off from PanelSwitchStatus."""
    if not isinstance(raw, int) or isinstance(raw, bool):
        return None
    if not raw & 0b10:
        return "auto"
    return "manual_off" if raw & 0b01 else "manual_on"


GATEWAY_FIRMWARE_PATTERN = re.compile(r"^ep\d+:(?:sZDO:FirmwareVersion|sGateway:GatewaySoftwareVersion)$")
GATEWAY_HARDWARE_PATTERN = re.compile(r"^ep\d+:sGateway:GatewayHardwareVersion$")
# Wi-Fi gateway (e.g. SAWZ600GW): signal strength in dBm and the connection to Salus Cloud (1 connected)
GATEWAY_RSSI_PATTERN = re.compile(r"^ep\d+:sGateway:WiFiRSSI$")
GATEWAY_CLOUD_PATTERN = re.compile(r"^ep\d+:sAWSIoT:CloudStatus$")
