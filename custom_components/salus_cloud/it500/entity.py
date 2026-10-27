"""Base entity of a Salus iT500 thermostat."""

from __future__ import annotations

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ..const import DOMAIN
from .coordinator import It500Coordinator
from .model import ZONE_1, It500Thermostat, Zone


class It500Entity(CoordinatorEntity[It500Coordinator]):
    """Entity of an iT500, named like the Salus Cloud entities: the device name, or a translated value name."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: It500Coordinator, device: It500Thermostat, key: str | None = None) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._device_id = device.id
        self._attr_device_info = coordinator.device_info(device)
        self._attr_unique_id = f"{DOMAIN}_{device.unique_id}"
        if key is None:
            self._attr_name = None
        else:
            self._attr_translation_key = key
            self._attr_unique_id += f"_{key}"

    @property
    def device(self) -> It500Thermostat | None:
        """Return current data of the thermostat."""
        return self.coordinator.get_device(self._device_id)

    @property
    def available(self) -> bool:
        """Return whether the thermostat's values were read recently."""
        device = self.device
        return super().available and device is not None and device.fresh


def zone_key(zone: Zone, key: str) -> str:
    """Return the key of a zone's entity: zone 1 keeps the plain key, zone 2 gets a "zone_2_" prefix."""
    return key if zone == ZONE_1 else f"zone_{zone.number}_{key}"
