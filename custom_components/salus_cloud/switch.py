"""Switch platform for Salus Cloud: relays and smart plugs, and on/off thermostat settings."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import SalusCloudCoordinator, SalusDevice
from .devices import is_climate_device, is_switch_device
from .entity import SalusEntity
from .settings import SWITCH_SETTINGS, SwitchSetting, find_key


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Salus Cloud relays and smart plugs."""
    coordinator: SalusCloudCoordinator = entry.runtime_data
    entities: list[SwitchEntity] = [
        SalusCloudSwitch(coordinator, device_id, device)
        for device_id, device in coordinator.data.items()
        if is_switch_device(device)
    ]
    for device_id, device in coordinator.data.items():
        if not is_climate_device(device):
            continue
        properties = device.get("_shadow_properties") or {}
        for setting in SWITCH_SETTINGS:
            if (key := find_key(properties, setting.pattern)) is not None:
                entities.append(SalusSettingSwitch(coordinator, device_id, device, setting, key))
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


class SalusSettingSwitch(SalusEntity, SwitchEntity):
    """An on/off thermostat setting (key lock, display always on, optimum start/stop, frost protection)."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SalusCloudCoordinator,
        device_id: str,
        device: SalusDevice,
        setting: SwitchSetting,
        key: str,
    ) -> None:
        """Initialize the setting for the property found when the device was set up."""
        super().__init__(coordinator, device_id, device)
        self._setting = setting
        self._property_key = key
        del self._attr_name
        self._attr_translation_key = setting.key
        self._attr_unique_id = f"{self._attr_unique_id}_{setting.key}"
        if setting.config:
            self._attr_entity_category = EntityCategory.CONFIG

    @property
    def is_on(self) -> bool | None:
        """Return whether the setting is on."""
        value = self.shadow_properties.get(self._property_key)
        if not isinstance(value, int) or isinstance(value, bool):
            return None
        return value != self._setting.off_value

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the setting on."""
        await self.coordinator.async_set_property(self._device_id, self._property_key, self._setting.on_value)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the setting off."""
        await self.coordinator.async_set_property(self._device_id, self._property_key, self._setting.off_value)
