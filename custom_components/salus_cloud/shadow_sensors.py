"""Separate sensor entities derived from reported shadow properties of thermostats.

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

HOLD_TYPE_OPTIONS = {HOLD_TYPE_SCHEDULE: "schedule", HOLD_TYPE_MANUAL: "manual", HOLD_TYPE_STANDBY: "frost_protection"}
SYSTEM_MODE_OPTIONS = {0: "off", 1: "auto", 4: "heat"}


def cluster_property(key: str) -> str:
    """Return the property without endpoint ("ep1:sTherS:SystemMode" -> "sTherS:SystemMode")."""
    endpoint, _, rest = key.partition(":")
    return rest if endpoint.startswith("ep") and rest else key


def property_name(key: str) -> str:
    """Return the property name without endpoint and cluster ("ep1:sTherS:SystemMode" -> "SystemMode")."""
    return key.rsplit(":", 1)[-1]


def scaled_value(key: str, value: Any) -> float | None:
    """Return a numeric value scaled by the _x100 / _x10 suffix of its property name."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    name = property_name(key)
    if name.endswith("_x100"):
        return round(value / 100, 2)
    if name.endswith("_x10"):
        return round(value / 10, 2)
    return float(value)


def _battery_voltage(key: str, value: Any) -> float | None:
    # iT600 reports BatteryVoltage in tenths of a volt without the _x10 suffix
    scaled = scaled_value(key, value)
    if scaled is not None and property_name(key) == "BatteryVoltage":
        return round(scaled / 10, 2)
    return scaled


def _option(options: dict[int, str]) -> Callable[[str, Any], str | None]:
    def value(_key: str, raw: Any) -> str | None:
        return options.get(raw) if isinstance(raw, int) else None

    return value


@dataclass(frozen=True, kw_only=True)
class ShadowSensorDescription:
    """Sensor created from one reported shadow property."""

    key: str
    name: str
    # Matches "cluster:name" of the property (without endpoint)
    pattern: re.Pattern[str]
    value: Callable[[str, Any], Any] = scaled_value
    device_class: SensorDeviceClass | None = None
    native_unit: str | None = None
    state_class: SensorStateClass | None = None
    entity_category: EntityCategory | None = None
    options: list[str] | None = None
    suggested_display_precision: int | None = None


SHADOW_SENSORS: tuple[ShadowSensorDescription, ...] = (
    ShadowSensorDescription(
        key="current_temperature",
        name="Temperature",
        pattern=re.compile(r"^s\w+:LocalTemperature(_x100)?$"),
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    ShadowSensorDescription(
        key="target_temperature",
        name="Target temperature",
        pattern=re.compile(r"^s\w+:HeatingSetpoint(_x100)?$"),
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
    ),
    ShadowSensorDescription(
        key="floor_temperature",
        name="Floor temperature",
        pattern=re.compile(r"^sTherS:FloorTemperature(_x100)?$"),
        value=lambda key, raw: temperature_value(key, raw),
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    ShadowSensorDescription(
        key="current_humidity",
        name="Humidity",
        # iT800 (IT800TX) and Quantum use the humidity measurement cluster sHumiS; other devices name it
        # ...Humidity (e.g. LocalHumidity_x100). Setpoints and commands are never readings.
        pattern=re.compile(r"^sHumiS:MeasuredValue(_x100)?$|^s\w+:(?!Set)(?!\w*Setpoint)\w*Humidity(_x100|_x10)?$"),
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit=PERCENTAGE,
        value=lambda key, raw: humidity_value(key, raw),
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
    ),
    ShadowSensorDescription(
        key="battery_voltage",
        name="Battery voltage",
        pattern=re.compile(r"^s\w+:BatteryVoltage(_x10|_x100)?$"),
        value=_battery_voltage,
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=1,
    ),
    ShadowSensorDescription(
        key="preset",
        name="Preset",
        pattern=re.compile(r"^s\w+:HoldType$"),
        value=_option(HOLD_TYPE_OPTIONS),
        device_class=SensorDeviceClass.ENUM,
        options=list(HOLD_TYPE_OPTIONS.values()),
    ),
    ShadowSensorDescription(
        key="system_mode",
        name="System mode",
        pattern=re.compile(r"^s\w+:SystemMode$"),
        value=_option(SYSTEM_MODE_OPTIONS),
        device_class=SensorDeviceClass.ENUM,
        options=list(SYSTEM_MODE_OPTIONS.values()),
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


def find_property(properties: dict[str, Any], pattern: re.Pattern[str]) -> str | None:
    """Return the first reported property (in sorted order) whose name matches the pattern."""
    return next(
        (key for key in sorted(properties) if ":Set" not in key and pattern.search(cluster_property(key))),
        None,
    )


RUNNING_STATE_PATTERN = re.compile(r"^s\w+:RunningState$")


HUMIDITY_PATTERN = next(description.pattern for description in SHADOW_SENSORS if description.key == "current_humidity")
# SQ610 (Quantum) thermostats report relative humidity in SunnySetpoint_x100, despite the name
# (found by Vlad Vesa; the local iT600 library reads it the same way).
SQ610_HUMIDITY = "ep9:sIT600TH:SunnySetpoint_x100"


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
        if not isinstance(raw, (int, float)) or isinstance(raw, bool) or raw < 0:
            return None
        return float(raw) if raw <= 100 else round(raw / 100, 2)
    return scaled_value(key, raw)


# Zigbee reports a missing temperature sensor (e.g. no floor probe connected) as 0x8000
INVALID_TEMPERATURE_X100 = (-32768, 32767, 0x8000)


def temperature_value(key: str, raw: Any) -> float | None:
    """Return a temperature, or None when the device reports that the sensor is missing."""
    if raw in INVALID_TEMPERATURE_X100:
        return None
    return scaled_value(key, raw)


def set_property(key: str) -> str:
    """Return the command property of a reported property ("ep1:sTherS:TempCalibration_x10" ->
    "ep1:sTherS:SetTempCalibration_x10")."""
    prefix, _, name = key.rpartition(":")
    return f"{prefix}:Set{name}"


# Read-only binary sensors
BATTERY_LOW_PATTERN = re.compile(r"^sPowerS:ErrorPowerSLowBattery$")
KEY_LOCK_PATTERN = re.compile(r"^sTherUIS:LockKey$")
# Error flags (0/1) such as sTherS:ErrorTherSTempSensor; *_d values are raw data, battery has its own sensor
ERROR_PATTERN = re.compile(r"^s\w+:Error(?!PowerSLowBattery)\w*(?<!_d)$")

# Thermostat limits
MIN_HEAT_SETPOINT_PATTERN = re.compile(r"^sTherS:MinHeatSetpoint_x100$")
MAX_HEAT_SETPOINT_PATTERN = re.compile(r"^sTherS:MaxHeatSetpoint_x100$")


def find_properties(properties: dict[str, Any], pattern: re.Pattern[str]) -> list[str]:
    """Return all reported properties (sorted) whose cluster:name matches the pattern."""
    return [key for key in sorted(properties) if ":Set" not in key and pattern.search(cluster_property(key))]


def active_errors(properties: dict[str, Any]) -> list[str]:
    """Return the names of the error flags that are set."""
    return [
        property_name(key)
        for key in find_properties(properties, ERROR_PATTERN)
        if isinstance(properties[key], (int, float)) and not isinstance(properties[key], bool) and properties[key]
    ]
