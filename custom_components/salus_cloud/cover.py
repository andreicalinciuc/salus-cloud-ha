"""Cover platform for Salus Cloud: roller shutters and blinds (RS600 in roller shutter mode).

The position is the RS600's ep1:sLevelS:CurrentLevel (0 closed, 100 open). Moving it sends
ep1:sLevelS:SetMoveToLevel as two hex digits followed by "FFFF", as the Salus app does ("64FFFF" opens fully).
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.cover import ATTR_POSITION, CoverDeviceClass, CoverEntity, CoverEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import SalusCloudCoordinator, SalusConfigEntry
from .device import SalusDevice
from .entity import SalusEntity
from .shadow import as_int

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SalusConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up roller shutters."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            SalusCover(coordinator, device, key)
            for device in coordinator.data.values()
            if (key := device.cover_property) is not None
        ]
    )


class SalusCover(SalusEntity, CoverEntity):
    """Roller shutter or blind, shown with the device name."""

    _attr_device_class = CoverDeviceClass.SHUTTER
    _attr_supported_features = CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.SET_POSITION

    def __init__(self, coordinator: SalusCloudCoordinator, device: SalusDevice, level_key: str) -> None:
        """Initialize the cover for the position property found when the device was set up."""
        super().__init__(coordinator, device)
        self._level_key = level_key

    @property
    def current_cover_position(self) -> int | None:
        """Return the position, 0 closed and 100 open."""
        value = as_int(self.shadow_properties.get(self._level_key))
        return None if value is None else max(0, min(100, value))

    @property
    def is_closed(self) -> bool | None:
        """Return whether the shutter is fully closed."""
        position = self.current_cover_position
        return None if position is None else position == 0

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the shutter fully."""
        await self.coordinator.async_set_cover_position(self._device_id, self._level_key, 100)

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the shutter fully."""
        await self.coordinator.async_set_cover_position(self._device_id, self._level_key, 0)

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Move the shutter to a position."""
        await self.coordinator.async_set_cover_position(self._device_id, self._level_key, int(kwargs[ATTR_POSITION]))
