"""Number platform for Salus Cloud: thermostat settings the Salus app also offers.

Only created when the thermostat reports the setting:
- temperature calibration (sTherS:TempCalibration_x10), -2.5 to +2.5 °C in 0.1 °C steps as in the Salus app;
- frost protection temperature (sComm:FrostSetpoint_x100), limited by the device's MinFrostSetpoint/MaxFrostSetpoint;
- lowest and highest heating setpoint (sTherS:MinHeatSetpoint_x100 / MaxHeatSetpoint_x100), 5 to 35 °C.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import SalusCloudCoordinator, SalusDevice
from .devices import is_climate_device
from .entity import SalusEntity
from .settings import signed_byte
from .shadow_sensors import find_property, scaled_value


@dataclass(frozen=True, kw_only=True)
class SalusNumberDescription:
    """Thermostat setting written through its Set* shadow property."""

    key: str
    pattern: re.Pattern[str]
    scale: int
    min_value: float
    max_value: float
    step: float
    min_pattern: re.Pattern[str] | None = None
    max_pattern: re.Pattern[str] | None = None
    signed_byte: bool = False


NUMBERS: tuple[SalusNumberDescription, ...] = (
    SalusNumberDescription(
        key="temperature_calibration",
        pattern=re.compile(r"^sTherS:TempCalibration_x10$"),
        scale=10,
        min_value=-2.5,
        max_value=2.5,
        step=0.1,
        signed_byte=True,
    ),
    SalusNumberDescription(
        key="frost_temperature",
        pattern=re.compile(r"^sComm:FrostSetpoint_x100$"),
        scale=100,
        min_value=5.0,
        max_value=17.0,
        step=0.5,
        min_pattern=re.compile(r"^sComm:MinFrostSetpoint_x100$"),
        max_pattern=re.compile(r"^sComm:MaxFrostSetpoint_x100$"),
    ),
    SalusNumberDescription(
        key="min_heat_setpoint",
        pattern=re.compile(r"^sTherS:MinHeatSetpoint_x100$"),
        scale=100,
        min_value=5.0,
        max_value=35.0,
        step=0.5,
    ),
    SalusNumberDescription(
        key="max_heat_setpoint",
        pattern=re.compile(r"^sTherS:MaxHeatSetpoint_x100$"),
        scale=100,
        min_value=5.0,
        max_value=35.0,
        step=0.5,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up thermostat settings."""
    coordinator: SalusCloudCoordinator = entry.runtime_data
    entities: list[NumberEntity] = []
    for device_id, device in coordinator.data.items():
        if not is_climate_device(device):
            continue
        properties = device.get("_shadow_properties") or {}
        for description in NUMBERS:
            if (key := find_property(properties, description.pattern)) is not None:
                entities.append(SalusNumber(coordinator, device_id, device, description, key))
    async_add_entities(entities)


class SalusNumber(SalusEntity, NumberEntity):
    """A thermostat setting."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_device_class = NumberDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_mode = NumberMode.BOX

    def __init__(
        self,
        coordinator: SalusCloudCoordinator,
        device_id: str,
        device: SalusDevice,
        description: SalusNumberDescription,
        key: str,
    ) -> None:
        """Initialize the setting for the property found when the device was set up."""
        super().__init__(coordinator, device_id, device)
        self._description = description
        self._property_key = key
        del self._attr_name
        self._attr_translation_key = description.key
        self._attr_unique_id = f"{self._attr_unique_id}_{description.key}"
        self._attr_native_step = description.step

    def _limit(self, pattern: re.Pattern[str] | None, default: float) -> float:
        properties = self.shadow_properties
        if pattern is None or (key := find_property(properties, pattern)) is None:
            return default
        value = scaled_value(key, properties[key])
        return default if value is None else value

    @property
    def native_min_value(self) -> float:
        """Return the lowest value the device accepts."""
        return self._limit(self._description.min_pattern, self._description.min_value)

    @property
    def native_max_value(self) -> float:
        """Return the highest value the device accepts."""
        return self._limit(self._description.max_pattern, self._description.max_value)

    @property
    def native_value(self) -> float | None:
        """Return the current setting."""
        raw = self.shadow_properties.get(self._property_key)
        if self._description.signed_byte:
            raw = signed_byte(raw)
        return scaled_value(self._property_key, raw)

    async def async_set_native_value(self, value: float) -> None:
        """Send the new setting to the thermostat."""
        await self.coordinator.async_set_property(
            self._device_id, self._property_key, round(value * self._description.scale)
        )
