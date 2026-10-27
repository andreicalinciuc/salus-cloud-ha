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

from .coordinator import SalusCloudCoordinator
from .device import SalusDevice
from .entity import SalusPropertyEntity
from .settings import SELECT_SETTINGS, SelectSetting
from .shadow import as_int


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up thermostat settings with a list of values."""
    coordinator: SalusCloudCoordinator = entry.runtime_data
    async_add_entities(
        [
            SalusSettingSelect(coordinator, device, setting, key)
            for device in coordinator.data.values()
            if device.is_thermostat
            for setting in SELECT_SETTINGS
            if (key := setting.find(device.properties)) is not None
        ]
    )


class SalusSettingSelect(SalusPropertyEntity, SelectEntity):
    """A thermostat setting with a fixed list of values."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, coordinator: SalusCloudCoordinator, device: SalusDevice, setting: SelectSetting, property_key: str
    ) -> None:
        """Initialize the setting for the property found when the device was set up."""
        super().__init__(coordinator, device, setting.key, property_key)
        self._setting = setting
        self._values = {option: value for value, option in setting.options.items()}
        self._attr_options = list(setting.options.values())

    @property
    def current_option(self) -> str | None:
        """Return the current value, or None when the device reports a value the Salus app does not offer."""
        value = as_int(self.raw_value)
        return None if value is None else self._setting.options.get(value)

    async def async_select_option(self, option: str) -> None:
        """Send the selected value to the thermostat."""
        if option not in self._values:
            raise HomeAssistantError(f"Unknown option {option}")
        await self.coordinator.async_set_property(self._device_id, self._property_key, self._values[option])
