"""Switch platform for Salus Cloud: relays and smart plugs, and on/off thermostat settings."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import SalusCloudCoordinator, SalusConfigEntry
from .device import SalusDevice
from .entity import SalusEntity, SalusPropertyEntity
from .settings import SWITCH_SETTINGS, SwitchSetting, find_setting
from .shadow import as_int

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SalusConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Salus Cloud relays and smart plugs."""
    coordinator = entry.runtime_data
    entities: list[SwitchEntity] = []
    for device in coordinator.data.values():
        if device.is_switch:
            entities.append(SalusCloudSwitch(coordinator, device))
        if device.is_thermostat:
            entities.extend(
                SalusSettingSwitch(coordinator, device, setting, key)
                for setting in SWITCH_SETTINGS
                if (key := find_setting(setting, device.properties)) is not None
            )
    async_add_entities(entities)


class SalusCloudSwitch(SalusEntity, SwitchEntity):
    """Salus relay or smart plug."""

    @property
    def is_on(self) -> bool | None:
        """Return whether the relay is on."""
        value = self.shadow_properties.get(self.property_names.on_off)
        return value == 1 if value is not None else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the relay on."""
        await self.coordinator.async_set_switch(self._device_id, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the relay off."""
        await self.coordinator.async_set_switch(self._device_id, False)


class SalusSettingSwitch(SalusPropertyEntity, SwitchEntity):
    """An on/off thermostat setting (key lock, display always on, optimum start/stop, frost protection)."""

    entity_description: SwitchSetting

    def __init__(
        self, coordinator: SalusCloudCoordinator, device: SalusDevice, setting: SwitchSetting, property_key: str
    ) -> None:
        """Initialize the setting for the property found when the device was set up."""
        super().__init__(coordinator, device, setting.key, property_key)
        self.entity_description = setting

    @property
    def is_on(self) -> bool | None:
        """Return whether the setting is on."""
        value = as_int(self.raw_value)
        return None if value is None else value != self.entity_description.off_value

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the setting on."""
        await self.coordinator.async_set_property(self._device_id, self._property_key, self.entity_description.on_value)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the setting off."""
        await self.coordinator.async_set_property(
            self._device_id, self._property_key, self.entity_description.off_value
        )
