"""Binary sensor platform for Salus Cloud."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import SalusCloudCoordinator, SalusConfigEntry
from .device import BINARY_SENSOR_CATEGORIES, IAS_ZONE_ALARM_PATTERN, SalusDevice
from .entity import SalusEntity, SalusGatewayEntity, SalusPropertyEntity
from .gateway import CLOUD_PATTERN, RELAY_PATTERN
from .it500 import binary_sensor as it500_binary_sensor
from .it500 import is_it500_entry
from .measurements import BATTERY_LOW_PATTERN as DEVICE_BATTERY_LOW_PATTERN
from .measurements import RELAY_STATUS_PATTERN
from .settings import is_setting
from .shadow import as_int, as_number, find_properties, find_property
from .thermostat import (
    BATTERY_LOW_PATTERN,
    ERROR_PATTERN,
    KEY_LOCK_PATTERN,
    RUNNING_STATE_PATTERN,
    active_errors,
    is_heating,
)

TRUE_VALUES = ("on", "true", "1", "open", "active")
TYPE_DEVICE_CLASSES = (("motion", BinarySensorDeviceClass.MOTION), ("occupancy", BinarySensorDeviceClass.OCCUPANCY))

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SalusConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Salus Cloud binary sensors."""
    if is_it500_entry(entry):
        await it500_binary_sensor.async_setup_entry(hass, entry, async_add_entities)
    else:
        async_add_entities(_entities(entry.runtime_data))


def _entities(coordinator: SalusCloudCoordinator) -> list[BinarySensorEntity]:
    entities: list[BinarySensorEntity] = []
    for device in coordinator.data.values():
        properties = device.properties
        if device.is_binary_sensor:
            entities.append(SalusCloudBinarySensor(coordinator, device))
        if not device.is_thermostat:
            if (key := find_property(properties, RELAY_STATUS_PATTERN)) is not None:
                entities.append(SalusHeatingBinarySensor(coordinator, device, "heating", key))
            if (key := find_property(properties, DEVICE_BATTERY_LOW_PATTERN)) is not None:
                entities.append(SalusFlagBinarySensor(coordinator, device, "battery_low", key))
            continue
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
    return entities


def _device_class(device: SalusDevice) -> BinarySensorDeviceClass | None:
    device_type = device.type
    model = device.model.upper()
    # WLS600 is the water leak sensor; SW600 / OS600 are door and window contacts
    if model.startswith("WLS"):
        return BinarySensorDeviceClass.MOISTURE
    if "SMOKE" in model:
        return BinarySensorDeviceClass.SMOKE
    if "door" in device_type or "window" in device_type or model.startswith(("SW600", "OS600")):
        return BinarySensorDeviceClass.DOOR
    if (device_class := BINARY_SENSOR_CATEGORIES.get(device.category or "")) is not None:
        return BinarySensorDeviceClass(device_class)
    return next((device_class for word, device_class in TYPE_DEVICE_CLASSES if word in device_type), None)


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in TRUE_VALUES
    if isinstance(value, int):
        return value == 1
    return None


class SalusCloudBinarySensor(SalusEntity, BinarySensorEntity):
    """Door, window, water leak, smoke or motion sensor.

    The state is the IAS zone alarm the device reports in its shadow; devices that do not report one fall back to
    the fields of the Salus device list.
    """

    def __init__(self, coordinator: SalusCloudCoordinator, device: SalusDevice) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, device)
        self._attr_device_class = _device_class(device)
        self._alarm_key = find_property(device.properties, IAS_ZONE_ALARM_PATTERN)

    @property
    def is_on(self) -> bool | None:
        """Return true while the sensor is open / alarmed."""
        if self._alarm_key is not None:
            value = as_int(self.shadow_properties.get(self._alarm_key))
            return None if value is None else value != 0
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
    """Whether the thermostat calls for heat (RunningState) or a TRV / receiver relay is on: "Heating" / "Idle"."""

    @property
    def is_on(self) -> bool | None:
        """Return true while the device heats."""
        return is_heating(self.raw_value)


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
