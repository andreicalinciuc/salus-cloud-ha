"""Thermostat values found in the shadow properties: sensors, flags, error flags and limits.

Properties are matched by cluster and name without the endpoint ("ep1:sHumiS:MeasuredValue_x100" is matched as
"sHumiS:MeasuredValue_x100"), so the same descriptions serve the iT600 (ep9) and iT800 (ep1/ep2) families.
An entity is only created when the device actually reports the property.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfElectricPotential, UnitOfTemperature

from .const import HOLD_TYPE_MANUAL, HOLD_TYPE_SCHEDULE, HOLD_TYPE_STANDBY
from .shadow import as_int, as_number, find_properties, find_property, property_name, scaled_value

HOLD_TYPE_OPTIONS = {HOLD_TYPE_SCHEDULE: "schedule", HOLD_TYPE_MANUAL: "manual", HOLD_TYPE_STANDBY: "frost_protection"}
SYSTEM_MODE_OPTIONS = {0: "off", 1: "auto", 4: "heat"}

# Heat demand (1 heating)
RUNNING_STATE_PATTERN = re.compile(r"^s\w+:RunningState$")
# Flags shown as binary sensors
BATTERY_LOW_PATTERN = re.compile(r"^sPowerS:ErrorPowerSLowBattery$")
KEY_LOCK_PATTERN = re.compile(r"^sTherUIS:LockKey$")
# Error flags (0/1) such as sTherS:ErrorTherSTempSensor; *_d values are raw data, battery has its own sensor
ERROR_PATTERN = re.compile(r"^s\w+:Error(?!PowerSLowBattery)\w*(?<!_d)$")
# Target temperature limits
MIN_HEAT_SETPOINT_PATTERN = re.compile(r"^sTherS:MinHeatSetpoint_x100$")
MAX_HEAT_SETPOINT_PATTERN = re.compile(r"^sTherS:MaxHeatSetpoint_x100$")

# iT800 (IT800TX) and Quantum use the humidity measurement cluster sHumiS; other devices name it ...Humidity
# (e.g. LocalHumidity_x100). Setpoints and commands are never readings.
HUMIDITY_PATTERN = re.compile(r"^sHumiS:MeasuredValue(_x100)?$|^s\w+:(?!Set)(?!\w*Setpoint)\w*Humidity(_x100|_x10)?$")
# SQ610 (Quantum) thermostats report relative humidity in SunnySetpoint_x100, despite the name
# (found by Vlad Vesa; the local iT600 library reads it the same way).
SQ610_HUMIDITY = "ep9:sIT600TH:SunnySetpoint_x100"

# Zigbee reports a missing temperature sensor (e.g. no floor probe connected) as 0x8000
INVALID_TEMPERATURE_X100 = (-32768, 32767, 0x8000)


def humidity_property(model: str | None, properties: dict[str, Any]) -> str | None:
    """Return the property holding the measured humidity of a device, if it reports one."""
    if (key := find_property(properties, HUMIDITY_PATTERN)) is not None:
        return key
    if (model or "").upper().startswith("SQ610") and SQ610_HUMIDITY in properties:
        return SQ610_HUMIDITY
    return None


def humidity_value(key: str, raw: Any) -> float | None:
    """Return humidity in percent; SQ610 reports it either as plain percent or x100 depending on firmware."""
    if key == SQ610_HUMIDITY:
        if (number := as_number(raw)) is None or number < 0:
            return None
        return float(number) if number <= 100 else round(number / 100, 2)
    return scaled_value(key, raw)


def temperature_value(key: str, raw: Any) -> float | None:
    """Return a temperature, or None when the device reports that the sensor is missing."""
    if raw in INVALID_TEMPERATURE_X100:
        return None
    return scaled_value(key, raw)


def battery_voltage(key: str, raw: Any) -> float | None:
    """Return the battery voltage; iT600 reports BatteryVoltage in tenths of a volt without the _x10 suffix."""
    scaled = scaled_value(key, raw)
    if scaled is not None and property_name(key) == "BatteryVoltage":
        return round(scaled / 10, 2)
    return scaled


def option_value(options: dict[int, str]) -> Callable[[str, Any], str | None]:
    """Return a converter from a reported number to one of the option names."""

    def value(_key: str, raw: Any) -> str | None:
        return options.get(raw) if as_int(raw) is not None else None

    return value


def active_errors(properties: dict[str, Any]) -> list[str]:
    """Return the names of the error flags that are set."""
    return [property_name(key) for key in find_properties(properties, ERROR_PATTERN) if as_number(properties[key])]


@dataclass(frozen=True, kw_only=True)
class ShadowSensorDescription:
    """Sensor created from one reported shadow property; key is also the translation key."""

    key: str
    # Matches "cluster:name" of the property (without endpoint)
    pattern: re.Pattern[str]
    value: Callable[[str, Any], Any] = scaled_value
    device_class: SensorDeviceClass | None = None
    native_unit: str | None = None
    state_class: SensorStateClass | None = None
    entity_category: EntityCategory | None = None
    options: list[str] | None = None
    suggested_display_precision: int | None = None

    def find(self, model: str, properties: dict[str, Any]) -> str | None:
        """Return the property of the device this sensor shows, None when the device does not report it."""
        if self.key == "current_humidity":
            return humidity_property(model, properties)
        return find_property(properties, self.pattern)


SHADOW_SENSORS: tuple[ShadowSensorDescription, ...] = (
    ShadowSensorDescription(
        key="current_temperature",
        pattern=re.compile(r"^s\w+:LocalTemperature(_x100)?$"),
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    ShadowSensorDescription(
        key="target_temperature",
        pattern=re.compile(r"^s\w+:HeatingSetpoint(_x100)?$"),
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
    ),
    ShadowSensorDescription(
        key="floor_temperature",
        pattern=re.compile(r"^sTherS:FloorTemperature(_x100)?$"),
        value=temperature_value,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    ShadowSensorDescription(
        key="current_humidity",
        pattern=HUMIDITY_PATTERN,
        value=humidity_value,
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
    ),
    ShadowSensorDescription(
        key="battery_voltage",
        pattern=re.compile(r"^s\w+:BatteryVoltage(_x10|_x100)?$"),
        value=battery_voltage,
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=1,
    ),
    ShadowSensorDescription(
        key="preset",
        pattern=re.compile(r"^s\w+:HoldType$"),
        value=option_value(HOLD_TYPE_OPTIONS),
        device_class=SensorDeviceClass.ENUM,
        options=list(HOLD_TYPE_OPTIONS.values()),
    ),
    ShadowSensorDescription(
        key="system_mode",
        pattern=re.compile(r"^s\w+:SystemMode$"),
        value=option_value(SYSTEM_MODE_OPTIONS),
        device_class=SensorDeviceClass.ENUM,
        options=list(SYSTEM_MODE_OPTIONS.values()),
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)
