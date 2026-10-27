"""Values of devices that are not thermostats (temperature sensors, contacts, TRVs, receivers) in their shadow.

Property names follow the Salus app: a remote temperature sensor (PS600) reports ep9:sTempS:MeasuredValue_x100,
contacts and leak sensors their battery alarm, TRVs paired to a thermostat and receivers their relay as
ep6:sIT600I:RelayStatus. As for thermostats, an entity is only created when the device reports the property.
"""

from __future__ import annotations

import re

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfElectricPotential, UnitOfTemperature

from .thermostat import HUMIDITY_PATTERN, ShadowSensorDescription, battery_voltage, humidity_value, temperature_value

BATTERY_LOW_PATTERN = re.compile(r"^(?:sPowerS:ErrorPowerSLowBattery|sIASZS:ErrorIASZSLowBattery)$")
# Relay of a TRV paired to a thermostat or of a receiver (1 on)
RELAY_STATUS_PATTERN = re.compile(r"^sIT600I:RelayStatus$")

DEVICE_SENSORS: tuple[ShadowSensorDescription, ...] = (
    ShadowSensorDescription(
        key="current_temperature",
        pattern=re.compile(r"^sTempS:MeasuredValue_x100$"),
        value_fn=temperature_value,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    ShadowSensorDescription(
        key="current_humidity",
        pattern=HUMIDITY_PATTERN,
        value_fn=humidity_value,
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
    ),
    ShadowSensorDescription(
        key="battery_voltage",
        pattern=re.compile(r"^sPowerS:BatteryVoltage(_x10|_x100)?$"),
        value_fn=battery_voltage,
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=1,
    ),
)
