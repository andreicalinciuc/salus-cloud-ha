"""Binary sensors of Salus iT500 thermostats: heating, frost protection, hot water, battery and cloud connection."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import It500ConfigEntry, It500Coordinator
from .entity import It500Entity, zone_key
from .model import It500Thermostat, Zone


@dataclass(frozen=True, kw_only=True)
class It500BinarySensorDescription(BinarySensorEntityDescription):
    """A flag of an iT500 thermostat."""

    value: Callable[[It500Thermostat], bool | None]


def _zone_flags(zone: Zone) -> list[It500BinarySensorDescription]:
    return [
        It500BinarySensorDescription(
            key=zone_key(zone, "heating"),
            translation_key=zone_key(zone, "heating"),
            value=lambda device: device.heating(zone),
        ),
        It500BinarySensorDescription(
            key=zone_key(zone, "frost_protection"),
            translation_key=zone_key(zone, "frost_protection"),
            value=lambda device: device.frost_active(zone),
        ),
    ]


HOT_WATER = It500BinarySensorDescription(
    key="hot_water", translation_key="hot_water", value=lambda device: device.hot_water_on
)
SYSTEM_FLAGS = [
    It500BinarySensorDescription(
        key="battery_low",
        translation_key="battery_low",
        device_class=BinarySensorDeviceClass.BATTERY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda device: device.battery_low,
    ),
    It500BinarySensorDescription(
        key="cloud_connection",
        translation_key="cloud_connection",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda device: device.online,
    ),
]


def _descriptions(device: It500Thermostat) -> list[It500BinarySensorDescription]:
    zones = [description for zone in device.zones for description in _zone_flags(zone)]
    return [*zones, *([HOT_WATER] if device.has_hot_water else []), *SYSTEM_FLAGS]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: It500ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the flags of each thermostat."""
    coordinator = entry.runtime_data
    async_add_entities(
        It500BinarySensor(coordinator, device, description)
        for device in coordinator.data.values()
        if device.is_thermostat
        for description in _descriptions(device)
    )


class It500BinarySensor(It500Entity, BinarySensorEntity):
    """A flag an iT500 reports."""

    entity_description: It500BinarySensorDescription

    def __init__(
        self, coordinator: It500Coordinator, device: It500Thermostat, description: It500BinarySensorDescription
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, device, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        """Return the flag."""
        return self.entity_description.value(self.device) if self.device else None
