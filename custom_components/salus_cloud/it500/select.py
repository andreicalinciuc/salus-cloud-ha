"""Hot water mode of Salus iT500 thermostats that also control hot water."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import It500ConfigEntry
from .entity import It500Entity
from .model import HOT_WATER_MODES


async def async_setup_entry(
    hass: HomeAssistant,
    entry: It500ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the hot water mode of thermostats with hot water."""
    coordinator = entry.runtime_data
    async_add_entities(
        It500HotWaterModeSelect(coordinator, device, "hot_water_mode")
        for device in coordinator.data.values()
        if device.has_hot_water
    )


class It500HotWaterModeSelect(It500Entity, SelectEntity):
    """Hot water mode: auto (schedule), once, on or off."""

    _attr_options = list(HOT_WATER_MODES)

    @property
    def current_option(self) -> str | None:
        """Return the hot water mode."""
        return self.device.hot_water_mode if self.device else None

    async def async_select_option(self, option: str) -> None:
        """Set the hot water mode."""
        await self.coordinator.async_set_hot_water_mode(self._device_id, option)
