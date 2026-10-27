"""Sensors of Salus iT500 thermostats: zone temperatures and radio signal."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import SIGNAL_STRENGTH_DECIBELS_MILLIWATT, EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import It500ConfigEntry, It500Coordinator
from .entity import It500Entity, zone_key
from .model import It500Thermostat, Zone


@dataclass(frozen=True, kw_only=True)
class It500SensorDescription(SensorEntityDescription):
    """A value of an iT500 thermostat."""

    value: Callable[[It500Thermostat], float | int | None]


def _zone_temperatures(zone: Zone) -> list[It500SensorDescription]:
    temperature = {
        "device_class": SensorDeviceClass.TEMPERATURE,
        "state_class": SensorStateClass.MEASUREMENT,
        "native_unit_of_measurement": UnitOfTemperature.CELSIUS,
    }
    return [
        It500SensorDescription(
            key=zone_key(zone, "current_temperature"),
            translation_key=zone_key(zone, "current_temperature"),
            value=lambda device: device.room_temperature(zone),
            **temperature,
        ),
        It500SensorDescription(
            key=zone_key(zone, "target_temperature"),
            translation_key=zone_key(zone, "target_temperature"),
            value=lambda device: device.setpoint(zone),
            **temperature,
        ),
    ]


SIGNAL_STRENGTH = It500SensorDescription(
    key="signal_strength",
    translation_key="signal_strength",
    device_class=SensorDeviceClass.SIGNAL_STRENGTH,
    state_class=SensorStateClass.MEASUREMENT,
    native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    entity_category=EntityCategory.DIAGNOSTIC,
    entity_registry_enabled_default=False,
    value=lambda device: device.rssi,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: It500ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the temperatures of each zone and the signal strength."""
    coordinator = entry.runtime_data
    async_add_entities(
        It500Sensor(coordinator, device, description)
        for device in coordinator.data.values()
        if device.is_thermostat
        for description in [*(d for zone in device.zones for d in _zone_temperatures(zone)), SIGNAL_STRENGTH]
    )


class It500Sensor(It500Entity, SensorEntity):
    """A value an iT500 reports."""

    entity_description: It500SensorDescription

    def __init__(
        self, coordinator: It500Coordinator, device: It500Thermostat, description: It500SensorDescription
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, device, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float | int | None:
        """Return the value."""
        return self.entity_description.value(self.device) if self.device else None
