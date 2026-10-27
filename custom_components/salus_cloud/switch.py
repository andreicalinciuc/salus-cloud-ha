"""Switch platform for Salus Cloud: relays and smart plugs, and on/off thermostat settings."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .coordinator import SalusCloudCoordinator, SalusConfigEntry
from .device import SalusDevice
from .entity import SalusEntity, SalusPropertyEntity
from .settings import SWITCH_SETTINGS, SwitchSetting, find_setting
from .shadow import as_int, endpoint_number

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
            outputs = device.on_off_properties
            # A roller shutter's relays drive its motor; only the first output stays a switch as before
            extra = outputs[1:] if device.cover_property is None else []
            entities.append(SalusCloudSwitch(coordinator, device))
            entities.extend(SalusCloudSwitch(coordinator, device, key) for key in extra)
        if device.is_thermostat:
            entities.extend(
                SalusSettingSwitch(coordinator, device, setting, key)
                for setting in SWITCH_SETTINGS
                if (key := find_setting(setting, device.properties)) is not None
            )
    async_add_entities(entities)


class SalusCloudSwitch(SalusEntity, SwitchEntity):
    """Salus relay or smart plug.

    The first output is shown with the device name. A device with more outputs (an RS600 or a relay with two
    channels) gets one "Relay <endpoint>" switch for each further one.
    """

    def __init__(self, coordinator: SalusCloudCoordinator, device: SalusDevice, on_off_key: str | None = None) -> None:
        """Initialize the first output, or the output reporting on_off_key."""
        super().__init__(coordinator, device, None if on_off_key is None else "relay")
        self._on_off_key = on_off_key
        if on_off_key is not None:
            number = str(endpoint_number(on_off_key))
            self._attr_unique_id = f"{DOMAIN}_{device.gateway_id}_{device.id}_relay_{number}"
            self._attr_translation_placeholders = {"number": number}

    @property
    def on_off_property(self) -> str:
        """Return the OnOff property of this output; the first output follows what the device reports."""
        if self._on_off_key is not None:
            return self._on_off_key
        outputs = self.device.on_off_properties if self.device else []
        return outputs[0] if outputs else self.property_names.on_off

    @property
    def is_on(self) -> bool | None:
        """Return whether the relay is on."""
        value = self.shadow_properties.get(self.on_off_property)
        return value == 1 if value is not None else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the relay on."""
        await self.coordinator.async_set_switch(self._device_id, True, self.on_off_property)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the relay off."""
        await self.coordinator.async_set_switch(self._device_id, False, self.on_off_property)


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
