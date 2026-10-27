"""Shadow property names reported and accepted by the supported Salus device families."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PropertyNames:
    """Property names of one device family's shadow document."""

    family: str
    hold_type: str
    system_mode: str
    running_state: str
    local_temperature: str
    heating_setpoint: str
    battery_voltage: str
    on_off: str
    set_hold_type: str
    set_heating_setpoint: str
    set_system_mode: str
    set_on_off: str
    # Some thermostats change HVAC mode through SystemMode instead of HoldType
    hvac_mode_uses_system_mode: bool = False
    # Setting a temperature also switches the thermostat to heating (SystemMode 4); a fan coil may be cooling
    setpoint_sets_heat_mode: bool = True


# Devices reporting under ep9, e.g. SQ610RF, HTRP-RF, TS600 and the relays
IT600 = PropertyNames(
    family="iT600",
    hold_type="ep9:sIT600TH:HoldType",
    system_mode="ep9:sIT600TH:SystemMode",
    running_state="ep9:sIT600TH:RunningState",
    local_temperature="ep9:sIT600TH:LocalTemperature_x100",
    heating_setpoint="ep9:sIT600TH:HeatingSetpoint_x100",
    battery_voltage="ep9:sBasicS:BatteryVoltage",
    on_off="ep9:sOnOffS:OnOff",
    set_hold_type="ep9:sIT600TH:SetHoldType",
    set_heating_setpoint="ep9:sIT600TH:SetHeatingSetpoint_x100",
    set_system_mode="ep9:sIT600TH:SetSystemMode",
    set_on_off="ep9:sOnOffS:SetOnOff",
)

# Devices reporting under ep1/ep2, e.g. IT800TX. They never report the ep9 property names.
IT800 = PropertyNames(
    family="iT800",
    hold_type="ep1:sComm:HoldType",
    system_mode="ep1:sTherS:SystemMode",
    running_state="ep1:sTherS:RunningState",
    local_temperature="ep1:sTherS:LocalTemperature_x100",
    heating_setpoint="ep1:sTherS:HeatingSetpoint_x100",
    battery_voltage="ep1:sPowerS:BatteryVoltage_x10",
    on_off="ep2:sOnOffS:OnOff",
    set_hold_type="ep1:sComm:SetHoldType",
    set_heating_setpoint="ep1:sTherS:SetHeatingSetpoint_x100",
    set_system_mode="ep1:sTherS:SetSystemMode",
    set_on_off="ep2:sOnOffS:SetOnOff",
    hvac_mode_uses_system_mode=True,
)


def zigbee_thermostat(endpoint: str) -> PropertyNames:
    """Return the names of a thermostat reporting sTherS / sComm under another endpoint than ep1.

    The FC600 fan coil reports them under ep9. It is switched off through the hold type alone, as the Salus app
    does, and keeps its system mode (heating or cooling) when a temperature is set.
    """
    return PropertyNames(
        family=f"sTherS ({endpoint})",
        hold_type=f"{endpoint}:sComm:HoldType",
        system_mode=f"{endpoint}:sTherS:SystemMode",
        running_state=f"{endpoint}:sTherS:RunningState",
        local_temperature=f"{endpoint}:sTherS:LocalTemperature_x100",
        heating_setpoint=f"{endpoint}:sTherS:HeatingSetpoint_x100",
        battery_voltage=f"{endpoint}:sPowerS:BatteryVoltage_x10",
        on_off=f"{endpoint}:sOnOffS:OnOff",
        set_hold_type=f"{endpoint}:sComm:SetHoldType",
        set_heating_setpoint=f"{endpoint}:sTherS:SetHeatingSetpoint_x100",
        set_system_mode=f"{endpoint}:sTherS:SetSystemMode",
        set_on_off=f"{endpoint}:sOnOffS:SetOnOff",
        setpoint_sets_heat_mode=False,
    )


DEFAULT_PROPERTY_NAMES = IT600

# A single ep1 or ep2 property is enough to identify the family; the ep9 defaults stay in place
# for the already supported devices, whose shadows do not contain them.
_IT800_PREFIXES = ("ep1:sTherS:", "ep1:sComm:", "ep1:sPowerS:", "ep2:sOnOffS:")
_THERMOSTAT_CLUSTER = re.compile(r"^(ep\d+):sTherS:(?:LocalTemperature|HeatingSetpoint)_x100$")


def detect_property_names(properties: dict[str, Any]) -> PropertyNames:
    """Return the property names of the family that reported these shadow properties."""
    if any(name.startswith(_IT800_PREFIXES) for name in properties):
        return IT800
    if any(name.startswith("ep9:sIT600TH:") for name in properties):
        return IT600
    for name in sorted(properties):
        if match := _THERMOSTAT_CLUSTER.match(name):
            return zigbee_thermostat(match.group(1))
    return DEFAULT_PROPERTY_NAMES
