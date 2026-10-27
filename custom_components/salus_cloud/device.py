"""Salus device as the integration sees it: its entry in the Salus device list plus its current shadow state."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .properties import DEFAULT_PROPERTY_NAMES, PropertyNames
from .shadow import endpoint, find_property

THERMOSTAT_MODELS = ("HTRP-RF", "TS600", "VS10", "VS20", "SQ610", "FC600", "IT800")
SWITCH_MODELS = ("RS600", "SPE600", "SR600")
BINARY_SENSOR_TYPES = ("door_sensor", "window_sensor", "motion_sensor", "binary_sensor")
# Alarm of a Zigbee IAS zone device (door / window contact, water leak, smoke), 1 while alarmed
IAS_ZONE_ALARM_PATTERN = re.compile(r"^sIASZS:ErrorIASZSAlarmed1$")
HUMIDITY_CLUSTER_PATTERN = re.compile(r"^sHumiS:MeasuredValue(_x100)?$")
# Any ZDO property shows the endpoint a device takes management commands on
ZDO_PATTERN = re.compile(r"^sZDO:\w+$")


@dataclass(frozen=True, kw_only=True)
class SalusDevice:
    """A device of a Salus gateway with its current state."""

    id: str
    code: str
    gateway_id: str
    # Entry of the Salus device list (name, model, type, ...)
    info: dict[str, Any] = field(default_factory=dict)
    # Reported shadow properties, overridden by commanded values the device has not reported yet
    properties: dict[str, Any] = field(default_factory=dict)
    names: PropertyNames = DEFAULT_PROPERTY_NAMES
    shadow_index: str | None = None
    # Whether the device reported its state recently
    fresh: bool = False

    @property
    def name(self) -> str:
        """Return the name given in the Salus app."""
        return self.info.get("name") or self.id

    @property
    def model(self) -> str:
        """Return the model, empty when unknown."""
        return self.info.get("model") or ""

    @property
    def type(self) -> str:
        """Return the device type of the Salus device list in lower case."""
        return (self.info.get("type") or "").lower()

    @property
    def is_thermostat(self) -> bool:
        """Return whether the device is a thermostat (a relay the user named "Thermostat ..." is not)."""
        return not self.is_switch and (
            self.type in ("thermostat", "climate")
            or self.model.upper().startswith(THERMOSTAT_MODELS)
            or "thermostat" in self.name.lower()
        )

    @property
    def is_switch(self) -> bool:
        """Return whether the device is a relay or a smart plug."""
        return self.type in ("switch", "relay") or self.model.upper().startswith(SWITCH_MODELS)

    @property
    def is_binary_sensor(self) -> bool:
        """Return whether the device is a door, window, water leak, smoke or motion sensor."""
        return (
            self.type in BINARY_SENSOR_TYPES
            or self.model.upper().startswith("WLS")
            or (
                not self.is_thermostat
                and not self.is_switch
                and find_property(self.properties, IAS_ZONE_ALARM_PATTERN) is not None
            )
        )

    @property
    def humidity_read_command(self) -> str | None:
        """Return the command making the device measure and report its humidity now, None without humidity cluster.

        Thermostats report humidity on their own only after a large change: an IT800TX kept one value for 16 hours.
        """
        key = find_property(self.properties, HUMIDITY_CLUSTER_PATTERN)
        return None if key is None else f"{endpoint(key)}:sHumiS:SetReadMeasuredValue"

    @property
    def refresh_command(self) -> str | None:
        """Return the command making the device report all its properties again, as the Salus app sends it."""
        key = find_property(self.properties, ZDO_PATTERN)
        return None if key is None else f"{endpoint(key)}:sZDO:SetRefresh_d"
