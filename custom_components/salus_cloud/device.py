"""Salus device as the integration sees it: its entry in the Salus device list plus its current shadow state."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .properties import DEFAULT_PROPERTY_NAMES, PropertyNames

THERMOSTAT_MODELS = ("HTRP-RF", "TS600", "VS10", "VS20", "SQ610", "FC600", "IT800")
SWITCH_MODELS = ("RS600", "SPE600", "SR600")
BINARY_SENSOR_TYPES = ("door_sensor", "window_sensor", "motion_sensor", "binary_sensor")


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
        """Return whether the device is a thermostat."""
        return (
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
        """Return whether the device is a door, window or motion sensor."""
        return self.type in BINARY_SENSOR_TYPES or self.model.upper().startswith("WLS")
