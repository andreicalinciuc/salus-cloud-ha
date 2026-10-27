"""Thermostat settings of the Salus app (Settings and Advanced settings of an IT800TX).

Settings are written through the matching Set* shadow property with the values the Salus app sends. They are
limited to the iT800 family (ep1 properties): iT600 (ep9) devices use other value encodings for the same names.
An entity is only created when the device reports the property.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from homeassistant.components.select import SelectEntityDescription
from homeassistant.components.switch import SwitchEntityDescription
from homeassistant.const import EntityCategory

from .shadow import find_property


@dataclass(frozen=True, kw_only=True)
class SwitchSetting(SwitchEntityDescription):
    """On/off setting stored in one shadow property; key is also the translation key."""

    # Matches the full property name (with endpoint)
    pattern: re.Pattern[str]
    on_value: int = 1
    off_value: int = 0


@dataclass(frozen=True, kw_only=True)
class SelectSetting(SelectEntityDescription):
    """Setting stored in one shadow property with a fixed list of values; key is also the translation key."""

    # Matches the full property name (with endpoint)
    pattern: re.Pattern[str]
    # Reported value -> option (translation key)
    values: dict[int, str]


def find_setting(setting: SwitchSetting | SelectSetting, properties: dict[str, Any]) -> str | None:
    """Return the property of the device holding the setting, None when the device does not report it."""
    return find_property(properties, setting.pattern, with_endpoint=True)


SWITCH_SETTINGS: tuple[SwitchSetting, ...] = (
    # Lock icon on the device page of the Salus app (1 locked, 0 unlocked), shown as a control
    SwitchSetting(key="key_lock", pattern=re.compile(r"^ep1:sTherUIS:LockKey$")),
    SwitchSetting(
        key="display_always_on",
        pattern=re.compile(r"^ep1:sComm:DisplayAlwaysOn$"),
        entity_category=EntityCategory.CONFIG,
    ),
    SwitchSetting(
        key="optimum_start",
        pattern=re.compile(r"^ep1:sComm:OptimizeStart$"),
        entity_category=EntityCategory.CONFIG,
    ),
    SwitchSetting(
        key="optimum_stop",
        pattern=re.compile(r"^ep1:sComm:OptimizeStop$"),
        entity_category=EntityCategory.CONFIG,
    ),
    # The app's "Frost protection" setting writes HolidayActive
    SwitchSetting(
        key="frost_protection",
        pattern=re.compile(r"^ep1:sComm:HolidayActive$"),
        entity_category=EntityCategory.CONFIG,
    ),
)

SELECT_SETTINGS: tuple[SelectSetting, ...] = (
    SelectSetting(
        key="display_brightness",
        pattern=re.compile(r"^ep1:sComm:LEDBrightness$"),
        values={204: "high", 64: "low"},
    ),
    SelectSetting(
        key="temperature_display_resolution",
        pattern=re.compile(r"^ep1:sComm:TempDisplayResolution$"),
        values={5: "half_degree", 1: "tenth_degree"},
    ),
    SelectSetting(
        key="heating_control",
        pattern=re.compile(r"^ep1:sComm:HeatingControlAlgorithm$"),
        values={
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
