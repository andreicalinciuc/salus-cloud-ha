"""Sensor platform for Salus Cloud."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, SIGNAL_STRENGTH_DECIBELS_MILLIWATT, EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import SalusCloudCoordinator, SalusConfigEntry
from .device import SalusDevice
from .entity import SalusEntity, SalusGatewayEntity, SalusPropertyEntity
from .gateway import PANEL_SWITCH_PATTERN, RECEIVER_MODE_OPTIONS, RSSI_PATTERN, receiver_mode
from .it500 import is_it500_entry
from .it500 import sensor as it500_sensor
from .measurements import DEVICE_SENSORS
from .shadow import as_int, as_number, find_property
from .thermostat import SHADOW_SENSORS, ShadowSensorDescription

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SalusConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Salus Cloud sensors."""
    if is_it500_entry(entry):
        await it500_sensor.async_setup_entry(hass, entry, async_add_entities)
        return
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = []
    for device in coordinator.data.values():
        if _has_temperature(device.info):
            entities.append(SalusCloudTemperatureSensor(coordinator, device))
        if _has_humidity(device.info):
            entities.append(SalusCloudHumiditySensor(coordinator, device))
        if _has_battery(device.info):
            entities.append(SalusCloudBatterySensor(coordinator, device))
        entities.extend(
            SalusShadowSensor(coordinator, device, description, key)
            for description in (SHADOW_SENSORS if device.is_thermostat else DEVICE_SENSORS)
            if (key := description.find(device.model, device.properties)) is not None
        )
    for gateway in coordinator.gateways:
        properties = coordinator.gateway_properties(gateway.id)
        if (key := find_property(properties, PANEL_SWITCH_PATTERN, with_endpoint=True)) is not None:
            entities.append(SalusReceiverModeSensor(coordinator, gateway.id, "receiver_mode", key))
        if (key := find_property(properties, RSSI_PATTERN, with_endpoint=True)) is not None:
            entities.append(SalusWifiSignalSensor(coordinator, gateway.id, "wifi_signal", key))
    async_add_entities(entities)


def _has_temperature(device: dict[str, Any]) -> bool:
    """Check if device is a standalone temperature sensor."""
    device_type = device.get("type", "").lower()
    return device_type == "temperature_sensor" or (device_type == "sensor" and "temperature" in device)


def _has_humidity(device: dict[str, Any]) -> bool:
    """Check if device has humidity sensor."""
    return "humidity" in device or ("status" in device and "humidity" in device["status"])


def _has_battery(device: dict[str, Any]) -> bool:
    """Check if device has battery information."""
    return "battery" in device or "battery_level" in device or ("status" in device and "battery" in device["status"])


def _value(data: dict[str, Any], fields: tuple[str, ...], scale_above_100: bool) -> float | None:
    """Return first present field from device data or its status, scaled from x100 format when needed."""
    for source in (data, data.get("status") if isinstance(data.get("status"), dict) else {}):
        for field in fields:
            if field in source:
                if (value := as_number(source[field])) is None:
                    return None
                if scale_above_100 and isinstance(value, int) and value > 100:
                    return value / 100.0
                return float(value)
    return None


class SalusCloudSensor(SalusEntity, SensorEntity):
    """Value of a sensor read from the Salus device list (temperature, humidity and battery sensors)."""

    def __init__(self, coordinator: SalusCloudCoordinator, device: SalusDevice, sensor_type: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, device, sensor_type)
        # The type only extends the unique id; the name comes from the device class ("Temperature")
        self._attr_translation_key = None

    @property
    def info(self) -> dict[str, Any]:
        """Return the entry of the device in the Salus device list."""
        return self.device.info if self.device else {}


class SalusCloudTemperatureSensor(SalusCloudSensor):
    """Temperature sensor for Salus Cloud devices."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(self, coordinator: SalusCloudCoordinator, device: SalusDevice) -> None:
        """Initialize the temperature sensor."""
        super().__init__(coordinator, device, "temperature")

    @property
    def native_value(self) -> float | None:
        """Return the temperature value."""
        return _value(self.info, ("temperature", "current_temperature", "LocalTemperature"), True)


class SalusCloudHumiditySensor(SalusCloudSensor):
    """Humidity sensor for Salus Cloud devices."""

    _attr_device_class = SensorDeviceClass.HUMIDITY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(self, coordinator: SalusCloudCoordinator, device: SalusDevice) -> None:
        """Initialize the humidity sensor."""
        super().__init__(coordinator, device, "humidity")

    @property
    def native_value(self) -> float | None:
        """Return the humidity value."""
        return _value(self.info, ("humidity", "current_humidity"), True)


class SalusCloudBatterySensor(SalusCloudSensor):
    """Battery sensor for Salus Cloud devices."""

    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(self, coordinator: SalusCloudCoordinator, device: SalusDevice) -> None:
        """Initialize the battery sensor."""
        super().__init__(coordinator, device, "battery")

    @property
    def native_value(self) -> float | None:
        """Return the battery level."""
        return _value(self.info, ("battery", "battery_level", "battery_percentage"), False)


class SalusShadowSensor(SalusPropertyEntity, SensorEntity):
    """One reported shadow property of a device as its own sensor."""

    entity_description: ShadowSensorDescription

    def __init__(
        self,
        coordinator: SalusCloudCoordinator,
        device: SalusDevice,
        description: ShadowSensorDescription,
        property_key: str,
    ) -> None:
        """Initialize the sensor for the property found when the device was set up."""
        super().__init__(coordinator, device, description.key, property_key)
        self.entity_description = description

    @property
    def native_value(self) -> float | str | None:
        """Return the converted property value."""
        raw = self.raw_value
        return None if raw is None else self.entity_description.value_fn(self._property_key, raw)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the shadow property the value comes from."""
        return {"shadow_property": self._property_key}


class SalusReceiverModeSensor(SalusGatewayEntity, SensorEntity):
    """Mode of a Wi-Fi receiver: automatic (thermostats decide) or switched on/off by hand on the receiver."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = RECEIVER_MODE_OPTIONS

    @property
    def native_value(self) -> str | None:
        """Return auto / manual_on / manual_off."""
        return receiver_mode(self.raw_value)


class SalusWifiSignalSensor(SalusGatewayEntity, SensorEntity):
    """Wi-Fi signal strength of a gateway."""

    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self) -> int | None:
        """Return the signal strength in dBm."""
        return as_int(self.raw_value)
