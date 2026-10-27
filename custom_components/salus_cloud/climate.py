"""Climate platform for Salus Cloud thermostats."""

from __future__ import annotations

import re
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import HOLD_TYPE_MANUAL, HOLD_TYPE_SCHEDULE, HOLD_TYPE_STANDBY
from .coordinator import SalusCloudCoordinator, SalusDevice
from .devices import is_climate_device
from .entity import SalusEntity
from .shadow_sensors import (
    MAX_HEAT_SETPOINT_PATTERN,
    MIN_HEAT_SETPOINT_PATTERN,
    find_property,
    humidity_property,
    humidity_value,
    scaled_value,
)

PRESET_SCHEDULE = "schedule"
PRESET_MANUAL = "manual"
PRESET_AWAY = "away"  # Stand-by with frost protection

PRESET_TO_HOLD_TYPE = {
    PRESET_SCHEDULE: HOLD_TYPE_SCHEDULE,
    PRESET_MANUAL: HOLD_TYPE_MANUAL,
    PRESET_AWAY: HOLD_TYPE_STANDBY,
}
HOLD_TYPE_TO_PRESET = {hold_type: preset for preset, hold_type in PRESET_TO_HOLD_TYPE.items()}
HOLD_TYPE_NAMES = {
    HOLD_TYPE_SCHEDULE: "Schedule",
    HOLD_TYPE_MANUAL: "Manual Hold",
    HOLD_TYPE_STANDBY: "Frost Protection",
}
SYSTEM_MODE_NAMES = {0: "Off", 1: "Auto", 4: "Heat"}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Salus Cloud thermostats."""
    coordinator: SalusCloudCoordinator = entry.runtime_data
    async_add_entities(
        [
            SalusCloudClimate(coordinator, device_id, device)
            for device_id, device in coordinator.data.items()
            if is_climate_device(device)
        ]
    )


class SalusCloudClimate(SalusEntity, ClimateEntity):
    """Salus thermostat."""

    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    # The thermostat is the main feature of its device: it is shown with the device name only
    _attr_has_entity_name = True
    # Labels and icons of the presets (schedule / manual / away) come from translations and icons.json
    _attr_translation_key = "thermostat"
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
    _attr_preset_modes = [PRESET_SCHEDULE, PRESET_MANUAL, PRESET_AWAY]
    _attr_target_temperature_step = 0.5

    def __init__(self, coordinator: SalusCloudCoordinator, device_id: str, device: SalusDevice) -> None:
        """Initialize the thermostat; existing entity ids are kept by the entity registry."""
        super().__init__(coordinator, device_id, device)
        self._attr_name = None

    def _limit(self, pattern: re.Pattern[str], default: float) -> float:
        properties = self.shadow_properties
        if (key := find_property(properties, pattern)) is None:
            return default
        value = scaled_value(key, properties[key])
        return value if value is not None and 0 < value < 50 else default

    @property
    def min_temp(self) -> float:
        """Return the lowest target temperature the thermostat accepts (MinHeatSetpoint when reported)."""
        return self._limit(MIN_HEAT_SETPOINT_PATTERN, 5.0)

    @property
    def max_temp(self) -> float:
        """Return the highest target temperature the thermostat accepts (MaxHeatSetpoint when reported)."""
        return self._limit(MAX_HEAT_SETPOINT_PATTERN, 35.0)

    def _temperature(self, name: str) -> float | None:
        value = self.shadow_properties.get(name)
        return value / 100 if value is not None else None

    @property
    def current_temperature(self) -> float | None:
        """Return the measured temperature."""
        return self._temperature(self.property_names.local_temperature)

    @property
    def current_humidity(self) -> float | None:
        """Return the measured relative humidity when the thermostat reports one."""
        properties = self.shadow_properties
        if (key := humidity_property(self.device_data.get("model"), properties)) is None:
            return None
        return humidity_value(key, properties[key])

    @property
    def target_temperature(self) -> float | None:
        """Return the target temperature."""
        return self._temperature(self.property_names.heating_setpoint)

    @property
    def hvac_mode(self) -> HVACMode | None:
        """Return off for stand-by or system mode off, heat otherwise."""
        properties = self.shadow_properties
        names = self.property_names
        if not properties:
            return None
        if properties.get(names.hold_type) == HOLD_TYPE_STANDBY or properties.get(names.system_mode) == 0:
            return HVACMode.OFF
        return HVACMode.HEAT

    @property
    def hvac_action(self) -> HVACAction | None:
        """Return whether the thermostat is heating right now."""
        hvac_mode = self.hvac_mode
        if hvac_mode is None:
            return None
        if hvac_mode == HVACMode.OFF:
            return HVACAction.OFF
        if self.shadow_properties.get(self.property_names.running_state) == 1:
            return HVACAction.HEATING
        return HVACAction.IDLE

    @property
    def preset_mode(self) -> str | None:
        """Return preset matching the hold type."""
        hold_type = self.shadow_properties.get(self.property_names.hold_type)
        if hold_type is None:
            return None
        return HOLD_TYPE_TO_PRESET.get(hold_type, PRESET_MANUAL)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set target temperature."""
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is not None:
            await self.coordinator.async_set_temperature(self._device_id, temperature)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set preset (synchronized across the gateway when enabled)."""
        await self.coordinator.async_set_hold_type(self._device_id, PRESET_TO_HOLD_TYPE[preset_mode])

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set off or heat, synchronized across the gateway when enabled."""
        await self.coordinator.async_set_hvac_mode(self._device_id, hvac_mode == HVACMode.HEAT)

    async def async_turn_on(self) -> None:
        """Turn heating on (follow schedule)."""
        await self.async_set_hvac_mode(HVACMode.HEAT)

    async def async_turn_off(self) -> None:
        """Turn heating off (stand-by)."""
        await self.async_set_hvac_mode(HVACMode.OFF)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return hold type, system mode, battery voltage and running state."""
        properties = self.shadow_properties
        names = self.property_names
        attributes: dict[str, Any] = {}
        if (hold_type := properties.get(names.hold_type)) is not None:
            attributes["hold_type"] = HOLD_TYPE_NAMES.get(hold_type, f"Unknown ({hold_type})")
        if (system_mode := properties.get(names.system_mode)) is not None:
            attributes["system_mode"] = SYSTEM_MODE_NAMES.get(system_mode, f"Unknown ({system_mode})")
        if (battery_voltage := properties.get(names.battery_voltage)) is not None:
            attributes["battery_voltage"] = f"{battery_voltage / 10:.1f}V"
        if (running_state := properties.get(names.running_state)) is not None:
            attributes["running_state"] = "Heating" if running_state == 1 else "Idle"
        return attributes
