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

from .coordinator import SalusCloudCoordinator, SalusDevice
from .devices import is_climate_device
from .entity import SalusEntity, SalusGatewayEntity
from .settings import GATEWAY_CLOUD_PATTERN, GATEWAY_RELAY_PATTERN, SWITCH_SETTINGS, find_key
from .shadow_sensors import (
    BATTERY_LOW_PATTERN,
    ERROR_PATTERN,
    KEY_LOCK_PATTERN,
    RUNNING_STATE_PATTERN,
    active_errors,
    find_properties,
    find_property,
)

BINARY_SENSOR_TYPES = ("door_sensor", "window_sensor", "motion_sensor", "binary_sensor")
TRUE_VALUES = ("on", "true", "1", "open", "active")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Salus Cloud binary sensors."""
    coordinator: SalusCloudCoordinator = entry.runtime_data
    entities: list[BinarySensorEntity] = [
        SalusCloudBinarySensor(coordinator, device_id, device, _get_device_class(device))
        for device_id, device in coordinator.data.items()
        if _is_binary_sensor_device(device)
    ]
    for device_id, device in coordinator.data.items():
        if not is_climate_device(device):
            continue
        properties = device.get("_shadow_properties") or {}
        if (key := find_property(properties, RUNNING_STATE_PATTERN)) is not None:
            entities.append(SalusHeatingBinarySensor(coordinator, device_id, device, key))
        if (key := find_property(properties, BATTERY_LOW_PATTERN)) is not None:
            entities.append(SalusFlagBinarySensor(coordinator, device_id, device, key, "battery_low"))
        # iT800 thermostats get a key lock switch instead
        if (key := find_property(properties, KEY_LOCK_PATTERN)) is not None and not any(
            setting.pattern.search(key) for setting in SWITCH_SETTINGS
        ):
            entities.append(SalusFlagBinarySensor(coordinator, device_id, device, key, "key_lock"))
        if find_properties(properties, ERROR_PATTERN):
            entities.append(SalusProblemBinarySensor(coordinator, device_id, device))
    for gateway in coordinator.gateways:
        properties = coordinator.gateway_properties(gateway.id)
        if (key := find_key(properties, GATEWAY_RELAY_PATTERN)) is not None:
            entities.append(SalusBoilerBinarySensor(coordinator, gateway.id, "boiler", key))
        if (key := find_key(properties, GATEWAY_CLOUD_PATTERN)) is not None:
            entities.append(SalusCloudConnectionBinarySensor(coordinator, gateway.id, "cloud_connection", key))
    async_add_entities(entities)


def _is_binary_sensor_device(device: dict[str, Any]) -> bool:
    """Determine if device is a binary sensor."""
    return device.get("type", "").lower() in BINARY_SENSOR_TYPES or device.get("model", "").upper().startswith("WLS")


def _get_device_class(device: dict[str, Any]) -> BinarySensorDeviceClass | None:
    """Determine binary sensor device class."""
    device_type = device.get("type", "").lower()
    if "door" in device_type or "window" in device_type or device.get("model", "").upper().startswith("WLS"):
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
    """Salus Cloud binary sensor."""

    def __init__(
        self,
        coordinator: SalusCloudCoordinator,
        device_id: str,
        device: SalusDevice,
        device_class: BinarySensorDeviceClass | None,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, device_id, device)
        self._attr_device_class = device_class

    @property
    def is_on(self) -> bool:
        """Return true if the binary sensor is on."""
        data = self.device_data
        for field in ("is_on", "state", "active", "triggered", "open"):
            if field in data and (value := _as_bool(data[field])) is not None:
                return value
        status = data.get("status")
        if isinstance(status, dict):
            for field in ("state", "active", "triggered"):
                if field in status and (value := _as_bool(status[field])) is not None:
                    return value
        return False


class SalusHeatingBinarySensor(SalusEntity, BinarySensorEntity):
    """Whether the thermostat is calling for heat right now (RunningState)."""

    _attr_translation_key = "heating"

    def __init__(self, coordinator: SalusCloudCoordinator, device_id: str, device: SalusDevice, key: str) -> None:
        """Initialize the heat demand sensor ("Heating" / "Idle" under the device)."""
        super().__init__(coordinator, device_id, device)
        self._property_key = key
        del self._attr_name
        self._attr_has_entity_name = True
        self._attr_unique_id = f"{self._attr_unique_id}_heating"

    @property
    def is_on(self) -> bool | None:
        """Return true while the thermostat demands heat."""
        value = self.shadow_properties.get(self._property_key)
        return None if value is None else value == 1


class SalusFlagBinarySensor(SalusEntity, BinarySensorEntity):
    """A 0/1 (or 0..n) property of a thermostat: low battery or key lock."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self, coordinator: SalusCloudCoordinator, device_id: str, device: SalusDevice, key: str, kind: str
    ) -> None:
        """Initialize the sensor for the property found when the device was set up."""
        super().__init__(coordinator, device_id, device)
        self._property_key = key
        del self._attr_name
        self._attr_translation_key = kind
        self._attr_unique_id = f"{self._attr_unique_id}_{kind}"
        if kind == "battery_low":
            self._attr_device_class = BinarySensorDeviceClass.BATTERY

    @property
    def is_on(self) -> bool | None:
        """Return true when the flag is set (any non-zero lock level counts as locked)."""
        value = self.shadow_properties.get(self._property_key)
        return None if not isinstance(value, (int, float)) else value != 0


class SalusProblemBinarySensor(SalusEntity, BinarySensorEntity):
    """On when the thermostat reports any error flag (e.g. a faulty temperature sensor)."""

    _attr_has_entity_name = True
    _attr_translation_key = "problem"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: SalusCloudCoordinator, device_id: str, device: SalusDevice) -> None:
        """Initialize the problem sensor."""
        super().__init__(coordinator, device_id, device)
        del self._attr_name
        self._attr_unique_id = f"{self._attr_unique_id}_problem"

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
        value = self.raw_value
        if not isinstance(value, int) or isinstance(value, bool):
            return None
        return value != 0


class SalusCloudConnectionBinarySensor(SalusGatewayEntity, BinarySensorEntity):
    """Whether the gateway reports a connection to Salus Cloud."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def is_on(self) -> bool | None:
        """Return true while the gateway is connected to Salus Cloud."""
        value = self.raw_value
        if not isinstance(value, int) or isinstance(value, bool):
            return None
        return value == 1
