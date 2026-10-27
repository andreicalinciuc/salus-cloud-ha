"""Thermostat settings of the Salus app (Settings and Advanced settings of an IT800TX).

Settings are written through the matching Set* shadow property with the values the Salus app sends. They are
limited to the iT800 family (ep1 properties): iT600 (ep9) devices use other value encodings for the same names.
An entity is only created when the device reports the property.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .shadow import find_property


@dataclass(frozen=True, kw_only=True)
class Setting:
    """Setting stored in one shadow property; key is also the translation key."""

    key: str
    # Matches the full property name (with endpoint)
    pattern: re.Pattern[str]

    def find(self, properties: dict[str, Any]) -> str | None:
        """Return the property of the device holding this setting, None when the device does not report it."""
        return find_property(properties, self.pattern, with_endpoint=True)


@dataclass(frozen=True, kw_only=True)
class SwitchSetting(Setting):
    """On/off setting."""

    on_value: int = 1
    off_value: int = 0
    # Shown under the device's configuration; the key lock is shown as a control
    config: bool = True


@dataclass(frozen=True, kw_only=True)
class SelectSetting(Setting):
    """Setting with a fixed list of values: reported value -> option (translation key)."""

    options: dict[int, str]


SWITCH_SETTINGS: tuple[SwitchSetting, ...] = (
    # Lock icon on the device page of the Salus app (1 locked, 0 unlocked)
    SwitchSetting(key="key_lock", pattern=re.compile(r"^ep1:sTherUIS:LockKey$"), config=False),
    SwitchSetting(key="display_always_on", pattern=re.compile(r"^ep1:sComm:DisplayAlwaysOn$")),
    SwitchSetting(key="optimum_start", pattern=re.compile(r"^ep1:sComm:OptimizeStart$")),
    SwitchSetting(key="optimum_stop", pattern=re.compile(r"^ep1:sComm:OptimizeStop$")),
    # The app's "Frost protection" setting writes HolidayActive
    SwitchSetting(key="frost_protection", pattern=re.compile(r"^ep1:sComm:HolidayActive$")),
)

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


def is_setting(key: str) -> bool:
    """Return whether the property is shown as a setting (and so not as a read-only sensor)."""
    return any(setting.pattern.search(key) for setting in (*SWITCH_SETTINGS, *SELECT_SETTINGS))
