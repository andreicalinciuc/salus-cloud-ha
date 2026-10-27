"""Climate entities of the heating zones of Salus iT500 thermostats."""

from __future__ import annotations

from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import It500ConfigEntry, It500Coordinator
from .entity import It500Entity
from .model import ZONE_1, It500Thermostat, Mode, Zone

PRESETS = [Mode.SCHEDULE, Mode.TEMPORARY_HOLD, Mode.MANUAL]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: It500ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up one climate entity per heating zone."""
    coordinator = entry.runtime_data
    async_add_entities(
        It500Climate(coordinator, device, zone)
        for device in coordinator.data.values()
        if device.is_thermostat
        for zone in device.zones
    )


class It500Climate(It500Entity, ClimateEntity):
    """Heating zone of an iT500: heat or off, with the schedule, temporary hold and manual modes as presets.

    Zone 1 is shown with the device name, zone 2 as "Zone 2".
    """

    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
    _attr_preset_modes = [str(preset) for preset in PRESETS]
    _attr_min_temp = 5.0
    _attr_max_temp = 35.0
    _attr_target_temperature_step = 0.1
    _attr_precision = 0.1

    def __init__(self, coordinator: It500Coordinator, device: It500Thermostat, zone: Zone) -> None:
        """Initialize the climate entity of a zone."""
        super().__init__(coordinator, device, None if zone == ZONE_1 else f"zone_{zone.number}")
        self._zone = zone
        if zone == ZONE_1:
            self._attr_translation_key = "thermostat"

    @property
    def available(self) -> bool:
        """Return whether the zone's values are known (zone 2 exists only on two zone systems)."""
        device = self.device
        return super().available and device is not None and self._zone in device.zones

    @property
    def _mode(self) -> Mode | None:
        return self.device.mode(self._zone) if self.device else None

    @property
    def current_temperature(self) -> float | None:
        """Return the measured temperature."""
        return self.device.room_temperature(self._zone) if self.device else None

    @property
    def target_temperature(self) -> float | None:
        """Return the target temperature."""
        return self.device.setpoint(self._zone) if self.device else None

    @property
    def hvac_mode(self) -> HVACMode | None:
        """Return heat, or off when the zone is off (frost protection only)."""
        if (mode := self._mode) is None:
            return None
        return HVACMode.OFF if mode is Mode.OFF else HVACMode.HEAT

    @property
    def hvac_action(self) -> HVACAction | None:
        """Return whether the boiler relay of the zone is on."""
        if self.device is None or (heating := self.device.heating(self._zone)) is None:
            return None
        if heating:
            return HVACAction.HEATING
        return HVACAction.OFF if self._mode is Mode.OFF else HVACAction.IDLE

    @property
    def preset_mode(self) -> str | None:
        """Return schedule, temporary hold or manual; none while the zone is off."""
        mode = self._mode
        return None if mode in (None, Mode.OFF) else str(mode)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set the target temperature (in schedule mode the thermostat holds it until the next change)."""
        if (hvac_mode := kwargs.get("hvac_mode")) is not None:
            await self.async_set_hvac_mode(hvac_mode)
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is not None:
            await self.coordinator.async_set_temperature(self._device_id, self._zone, float(temperature))

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Switch the zone off, or on again in the mode it had."""
        if hvac_mode == HVACMode.OFF:
            await self.coordinator.async_set_mode(self._device_id, self._zone, Mode.OFF)
        elif self._mode is Mode.OFF:
            await self.coordinator.async_turn_on(self._device_id, self._zone)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Select schedule, temporary hold or manual mode."""
        await self.coordinator.async_set_mode(self._device_id, self._zone, Mode(preset_mode))

    async def async_turn_on(self) -> None:
        """Turn the zone on."""
        await self.async_set_hvac_mode(HVACMode.HEAT)

    async def async_turn_off(self) -> None:
        """Turn the zone off."""
        await self.async_set_hvac_mode(HVACMode.OFF)
