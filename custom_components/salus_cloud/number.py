"""Number platform for Salus Cloud: thermostat settings the Salus app also offers.

Only created when the thermostat reports the setting:
- temperature calibration (sTherS:TempCalibration_x10), -2.5 to +2.5 °C in 0.1 °C steps as in the Salus app;
- frost protection temperature (sComm:FrostSetpoint_x100), limited by the device's MinFrostSetpoint/MaxFrostSetpoint;
- lowest and highest heating setpoint (sTherS:MinHeatSetpoint_x100 / MaxHeatSetpoint_x100), 5 to 35 °C.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberEntityDescription, NumberMode
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import SalusCloudCoordinator, SalusConfigEntry
from .device import SalusDevice
from .entity import SalusPropertyEntity
from .shadow import find_property, scaled_value, signed_byte

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class SalusNumberDescription(NumberEntityDescription):
    """Thermostat setting written through its Set* shadow property; key is also the translation key.

    native_min_value / native_max_value apply unless the device reports its own limits (min_pattern / max_pattern).
    """

    pattern: re.Pattern[str]
    scale: int
    min_pattern: re.Pattern[str] | None = None
    max_pattern: re.Pattern[str] | None = None
    signed_byte: bool = False


NUMBERS: tuple[SalusNumberDescription, ...] = (
    SalusNumberDescription(
        key="temperature_calibration",
        pattern=re.compile(r"^sTherS:TempCalibration_x10$"),
        scale=10,
        native_min_value=-2.5,
        native_max_value=2.5,
        native_step=0.1,
        signed_byte=True,
    ),
    SalusNumberDescription(
        key="frost_temperature",
        pattern=re.compile(r"^sComm:FrostSetpoint_x100$"),
        scale=100,
        native_min_value=5.0,
        native_max_value=17.0,
        native_step=0.5,
        min_pattern=re.compile(r"^sComm:MinFrostSetpoint_x100$"),
        max_pattern=re.compile(r"^sComm:MaxFrostSetpoint_x100$"),
    ),
    SalusNumberDescription(
        key="min_heat_setpoint",
        pattern=re.compile(r"^sTherS:MinHeatSetpoint_x100$"),
        scale=100,
        native_min_value=5.0,
        native_max_value=35.0,
        native_step=0.5,
    ),
    SalusNumberDescription(
        key="max_heat_setpoint",
        pattern=re.compile(r"^sTherS:MaxHeatSetpoint_x100$"),
        scale=100,
        native_min_value=5.0,
        native_max_value=35.0,
        native_step=0.5,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SalusConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up thermostat settings."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            SalusNumber(coordinator, device, description, key)
            for device in coordinator.data.values()
            if device.is_thermostat
            for description in NUMBERS
            if (key := find_property(device.properties, description.pattern)) is not None
        ]
    )


class SalusNumber(SalusPropertyEntity, NumberEntity):
    """A thermostat setting."""

    entity_description: SalusNumberDescription

    _attr_entity_category = EntityCategory.CONFIG
    _attr_device_class = NumberDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_mode = NumberMode.BOX

    def __init__(
        self,
        coordinator: SalusCloudCoordinator,
        device: SalusDevice,
        description: SalusNumberDescription,
        property_key: str,
    ) -> None:
        """Initialize the setting for the property found when the device was set up."""
        super().__init__(coordinator, device, description.key, property_key)
        self.entity_description = description

    def _limit(self, pattern: re.Pattern[str] | None, default: float) -> float:
        properties = self.shadow_properties
        if pattern is None or (key := find_property(properties, pattern)) is None:
            return default
        value = scaled_value(key, properties[key])
        return default if value is None else value

    @property
    def native_min_value(self) -> float:
        """Return the lowest value the device accepts."""
        return self._limit(self.entity_description.min_pattern, self.entity_description.native_min_value)

    @property
    def native_max_value(self) -> float:
        """Return the highest value the device accepts."""
        return self._limit(self.entity_description.max_pattern, self.entity_description.native_max_value)

    @property
    def native_value(self) -> float | None:
        """Return the current setting."""
        raw = self.raw_value
        if self.entity_description.signed_byte:
            raw = signed_byte(raw)
        return scaled_value(self._property_key, raw)

    async def async_set_native_value(self, value: float) -> None:
        """Send the new setting to the thermostat."""
        await self.coordinator.async_set_property(
            self._device_id, self._property_key, round(value * self.entity_description.scale)
        )
