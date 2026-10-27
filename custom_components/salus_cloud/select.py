"""Select platform for Salus Cloud: thermostat settings with a fixed list of values (iT800 family).

Display brightness, temperature display resolution and heating control (hysteresis or TPI), with the values the
Salus app sends. Only created when the thermostat reports the setting.
"""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import SalusCloudCoordinator, SalusDevice
from .devices import is_climate_device
from .entity import SalusEntity
from .settings import SELECT_SETTINGS, SelectSetting, find_key


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up thermostat settings with a list of values."""
    coordinator: SalusCloudCoordinator = entry.runtime_data
    entities: list[SelectEntity] = []
    for device_id, device in coordinator.data.items():
        if not is_climate_device(device):
            continue
        properties = device.get("_shadow_properties") or {}
        for setting in SELECT_SETTINGS:
            if (key := find_key(properties, setting.pattern)) is not None:
                entities.append(SalusSettingSelect(coordinator, device_id, device, setting, key))
    async_add_entities(entities)


class SalusSettingSelect(SalusEntity, SelectEntity):
    """A thermostat setting with a fixed list of values."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: SalusCloudCoordinator,
        device_id: str,
        device: SalusDevice,
        setting: SelectSetting,
        key: str,
    ) -> None:
        """Initialize the setting for the property found when the device was set up."""
        super().__init__(coordinator, device_id, device)
        self._setting = setting
        self._property_key = key
        self._values = {option: value for value, option in setting.options.items()}
        del self._attr_name
        self._attr_translation_key = setting.key
        self._attr_unique_id = f"{self._attr_unique_id}_{setting.key}"
        self._attr_options = list(setting.options.values())

    @property
    def current_option(self) -> str | None:
        """Return the current value, or None when the device reports a value the Salus app does not offer."""
        value = self.shadow_properties.get(self._property_key)
        return self._setting.options.get(value) if isinstance(value, int) and not isinstance(value, bool) else None

    async def async_select_option(self, option: str) -> None:
        """Send the selected value to the thermostat."""
        if option not in self._values:
            raise HomeAssistantError(f"Unknown option {option}")
        await self.coordinator.async_set_property(self._device_id, self._property_key, self._values[option])
