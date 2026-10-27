"""Refresh button of Salus iT500 thermostats."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import It500ConfigEntry
from .entity import It500Entity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: It500ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up a refresh button per thermostat."""
    coordinator = entry.runtime_data
    async_add_entities(
        It500RefreshButton(coordinator, device, "refresh")
        for device in coordinator.data.values()
        if device.is_thermostat
    )


class It500RefreshButton(It500Entity, ButtonEntity):
    """Wakes the thermostat, which then reports all its values within seconds."""

    async def async_press(self) -> None:
        """Send the refresh request; the values are read again shortly after."""
        await self.coordinator.async_refresh_device(self._device_id)
