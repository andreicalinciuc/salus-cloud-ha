"""Binary sensor platform for Salus Cloud."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import SalusCloudCoordinator
from .device import SalusDevice
from .entity import SalusEntity, SalusGatewayEntity, SalusPropertyEntity
from .gateway import CLOUD_PATTERN, RELAY_PATTERN
from .settings import is_setting
from .shadow import as_int, as_number, find_properties, find_property
from .thermostat import BATTERY_LOW_PATTERN, ERROR_PATTERN, KEY_LOCK_PATTERN, RUNNING_STATE_PATTERN, active_errors

TRUE_VALUES = ("on", "true", "1", "open", "active")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Salus Cloud binary sensors."""
    coordinator: SalusCloudCoordinator = entry.runtime_data
    entities: list[BinarySensorEntity] = []
    for device in coordinator.data.values():
        if device.is_binary_sensor:
            entities.append(SalusCloudBinarySensor(coordinator, device))
        if not device.is_thermostat:
            continue
        properties = device.properties
        if (key := find_property(properties, RUNNING_STATE_PATTERN)) is not None:
            entities.append(SalusHeatingBinarySensor(coordinator, device, "heating", key))
        if (key := find_property(properties, BATTERY_LOW_PATTERN)) is not None:
            entities.append(SalusFlagBinarySensor(coordinator, device, "battery_low", key))
        # iT800 thermostats get a key lock switch instead
        if (key := find_property(properties, KEY_LOCK_PATTERN)) is not None and not is_setting(key):
            entities.append(SalusFlagBinarySensor(coordinator, device, "key_lock", key))
        if find_properties(properties, ERROR_PATTERN):
            entities.append(SalusProblemBinarySensor(coordinator, device, "problem"))
    for gateway in coordinator.gateways:
        properties = coordinator.gateway_properties(gateway.id)
        if (key := find_property(properties, RELAY_PATTERN, with_endpoint=True)) is not None:
            entities.append(SalusBoilerBinarySensor(coordinator, gateway.id, "boiler", key))
        if (key := find_property(properties, CLOUD_PATTERN, with_endpoint=True)) is not None:
            entities.append(SalusCloudConnectionBinarySensor(coordinator, gateway.id, "cloud_connection", key))
    async_add_entities(entities)


def _device_class(device: SalusDevice) -> BinarySensorDeviceClass | None:
    device_type = device.type
    if "door" in device_type or "window" in device_type or device.model.upper().startswith("WLS"):
        return BinarySensorDeviceClass.DOOR
    if "motion" in device_type:
        return BinarySensorDeviceClass.MOTION
    if "occupancy" in device_type:
        return BinarySensorDeviceClass.OCCUPANCY
    return None


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in TRUE_VALUES
    if isinstance(value, int):
        return value == 1
    return None


class SalusCloudBinarySensor(SalusEntity, BinarySensorEntity):
    """Door, window or motion sensor; the state is read from the Salus device list."""

    def __init__(self, coordinator: SalusCloudCoordinator, device: SalusDevice) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, device)
        self._attr_device_class = _device_class(device)

    @property
    def is_on(self) -> bool:
        """Return true if the binary sensor is on."""
        data = self.device.info if self.device else {}
        for field in ("is_on", "state", "active", "triggered", "open"):
            if field in data and (value := _as_bool(data[field])) is not None:
                return value
        status = data.get("status")
        if isinstance(status, dict):
            for field in ("state", "active", "triggered"):
                if field in status and (value := _as_bool(status[field])) is not None:
                    return value
        return False


class SalusHeatingBinarySensor(SalusPropertyEntity, BinarySensorEntity):
    """Whether the thermostat is calling for heat right now (RunningState): "Heating" / "Idle"."""

    @property
    def is_on(self) -> bool | None:
        """Return true while the thermostat demands heat."""
        value = self.raw_value
        return None if value is None else value == 1


class SalusFlagBinarySensor(SalusPropertyEntity, BinarySensorEntity):
    """A 0/1 (or 0..n) property of a thermostat: low battery or key lock."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: SalusCloudCoordinator, device: SalusDevice, key: str, property_key: str) -> None:
        """Initialize the sensor for the property found when the device was set up."""
        super().__init__(coordinator, device, key, property_key)
        if key == "battery_low":
            self._attr_device_class = BinarySensorDeviceClass.BATTERY

    @property
    def is_on(self) -> bool | None:
        """Return true when the flag is set (any non-zero lock level counts as locked)."""
        value = as_number(self.raw_value)
        return None if value is None else value != 0


class SalusProblemBinarySensor(SalusEntity, BinarySensorEntity):
    """On when the thermostat reports any error flag (e.g. a faulty temperature sensor)."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def is_on(self) -> bool | None:
        """Return true while any error flag is set."""
        if not self.shadow_properties:
            return None
        return bool(active_errors(self.shadow_properties))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the error flags that are set."""
        return {"errors": active_errors(self.shadow_properties)}


class SalusBoilerBinarySensor(SalusGatewayEntity, BinarySensorEntity):
    """Boiler relay of a Wi-Fi receiver ("Heating" / "Idle")."""

    @property
    def is_on(self) -> bool | None:
        """Return true while the receiver switches the boiler on."""
        value = as_int(self.raw_value)
        return None if value is None else value != 0


class SalusCloudConnectionBinarySensor(SalusGatewayEntity, BinarySensorEntity):
    """Whether the gateway reports a connection to Salus Cloud."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def is_on(self) -> bool | None:
        """Return true while the gateway is connected to Salus Cloud."""
        value = as_int(self.raw_value)
        return None if value is None else value == 1
