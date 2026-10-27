"""Salus device as the integration sees it: its entry in the Salus device list plus its current shadow state."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .properties import DEFAULT_PROPERTY_NAMES, PropertyNames
from .shadow import endpoint, endpoint_number, find_properties, find_property

THERMOSTAT_MODELS = ("HTRP-RF", "TS600", "VS10", "VS20", "SQ610", "FC600", "IT800")
SWITCH_MODELS = ("RS600", "SPE600", "SR600")
BINARY_SENSOR_TYPES = ("door_sensor", "window_sensor", "motion_sensor", "binary_sensor")

# Category ids of the Salus device list ("category": {"category_id": ...}), as the Salus app groups devices
THERMOSTAT_CATEGORIES = {
    "3",  # thermostats (older category)
    "11",  # TRVs with their own thermostat (CTLV630)
    "12",  # iT600 thermostats (HTRP-RF, HTRS-RF, TS600, VS10/VS20)
    "13",  # Quantum thermostats (SQ610)
    "15",  # dial RF thermostats (SQ605)
    "32",  # fan coil thermostats (FC600)
    "38",  # RF thermostats (RSQ800WRF)
    "47",  # iT800TX thermostats
    "202",  # Elypso thermostats (C900T, EL600T)
    "204",  # TRV3RF
    "205",  # IT700TX
    "208",  # IT710TX
    "210",  # Quantum Plus thermostats (SQ620)
    "211",  # fan coil thermostats reporting sTherS under ep9
}
SWITCH_CATEGORIES = {
    "4",  # smart relays (SR600, SC812ZB, SC824ZB)
    "7",  # smart plugs (SP600, SPE600)
    "27",  # light switches
    "30",  # roller shutters (RS600), relay outputs
    "34",  # smart outlets
}
# Category -> Home Assistant binary sensor device class
BINARY_SENSOR_CATEGORIES = {
    "5": "moisture",  # water leak sensors (WLS600)
    "9": "window",  # window monitors (SW600, OS600)
    "18": "motion",  # motion sensors (MS600)
    "23": "smoke",  # smoke detectors
    "24": "door",  # door monitors
    "209": "heat",  # heat detectors
}
# Categories of devices that are known not to be thermostats, whatever their model or name
OTHER_CATEGORIES = {
    "1",  # gateways
    "6",  # buttons, repeaters, receivers and wiring centres
    "10",  # TRVs controlled by a thermostat (relay only)
    "20",  # remote temperature sensors
    "28",  # hot water timers
    *SWITCH_CATEGORIES,
    *BINARY_SENSOR_CATEGORIES,
}
# Models of the Salus app's model catalog (non-alphanumeric characters as "_") and their category, used when the
# device list has no category
MODEL_CATEGORIES = {
    # Hot water timers (not supported yet); listed so "TS600HW" is not taken for a TS600 thermostat
    **dict.fromkeys(("it600HW", "it600HW_AC", "it600HWNH", "it600HWNH_AC", "TS600HW", "NTVS41HW"), "28"),
    **dict.fromkeys(("CTLV630",), "11"),
    **dict.fromkeys(
        ("HTR_RF_20_", "HTRP_RF_50_", "HTRS_RF_30_", "it600ThermHW", "it600ThermHWNH", "NTVS41", "TS600"), "12"
    ),
    **dict.fromkeys(
        ("SQ610", "SQ610NH", "SQ610RF", "SQ610RFNH", "SQ610RFNH1", "NTSQ610NH", "NTSQ610RFNH", "SQ610_WB_"), "13"
    ),
    **dict.fromkeys(("SQ605RF_WB_", "NTSQ605RF", "AJSQ605RF", "ALTHCSQ605RF"), "15"),
    **dict.fromkeys(("FC600", "FC600NH"), "32"),
    **dict.fromkeys(("RSQ800WRF", "ALTHRSQ800WRF"), "38"),
    **dict.fromkeys(("IT800TX",), "47"),
    **dict.fromkeys(("C900T", "EL600T"), "202"),
    **dict.fromkeys(("TRV3RF",), "204"),
    **dict.fromkeys(("IT700TX",), "205"),
    **dict.fromkeys(("IT710TX",), "208"),
    **dict.fromkeys(("SQ620B", "SQ620BRF"), "210"),
    **dict.fromkeys(("SR600", "SC812ZB", "SC824ZB"), "4"),
    **dict.fromkeys(("SP600", "SPE600", "CTLP631", "CTLP632", "SX885ZB"), "7"),
    **dict.fromkeys(("45857",), "27"),
    **dict.fromkeys(("RS600",), "30"),
    **dict.fromkeys(("43102",), "34"),
    **dict.fromkeys(("WLS600", "moisturev4", "SS901ZB", "3315_G", "3315_S"), "5"),
    **dict.fromkeys(("SW600", "OS600", "NTSW600", "SS882ZB", "SS912ZB", "HDW10ZB", "CTLS634"), "9"),
    **dict.fromkeys(("MS600", "MS610", "PIRSensor_EM", "3041", "3043"), "18"),
    **dict.fromkeys(("SmokeSensor_EM", "SMSZB_120"), "23"),
    **dict.fromkeys(("SS881ZB",), "24"),
    **dict.fromkeys(("HESZB_120",), "209"),
    **dict.fromkeys(("PS600", "CTLS631", "CTLS632", "CTLS632E", "CTLS633", "HTS10ZB", "SS909ZB"), "20"),
}
_MODEL_KEY = re.compile(r"[^A-Za-z0-9]")
# Alarm of a Zigbee IAS zone device (door / window contact, water leak, smoke, motion), 1 while alarmed
IAS_ZONE_ALARM_PATTERN = re.compile(r"^sIASZS:ErrorIASZSAlarmed1$")
ON_OFF_PATTERN = re.compile(r"^sOnOffS:OnOff$")
# Position of a roller shutter (RS600): 0 closed ... 100 open
LEVEL_PATTERN = re.compile(r"^sLevelS:CurrentLevel$")
# RS600 output mode (sButtonS:Mode of the level endpoint): 1 one relay, 3 two relays, 5 / 6 roller shutter or blind
RELAY_OUTPUT_MODES = (1, 3)
HUMIDITY_CLUSTER_PATTERN = re.compile(r"^sHumiS:MeasuredValue(_x100)?$")
# Any ZDO property shows the endpoint a device takes management commands on
ZDO_PATTERN = re.compile(r"^sZDO:\w+$")


@dataclass(frozen=True, kw_only=True)
class SalusDevice:
    """A device of a Salus gateway with its current state."""

    id: str
    code: str
    gateway_id: str
    # Entry of the Salus device list (name, model, type, ...)
    info: dict[str, Any] = field(default_factory=dict)
    # Reported shadow properties, overridden by commanded values the device has not reported yet
    properties: dict[str, Any] = field(default_factory=dict)
    names: PropertyNames = DEFAULT_PROPERTY_NAMES
    shadow_index: str | None = None
    # Whether the device reported its state recently
    fresh: bool = False

    @property
    def name(self) -> str:
        """Return the name given in the Salus app."""
        return self.info.get("name") or self.id

    @property
    def model(self) -> str:
        """Return the model, empty when unknown."""
        return self.info.get("model") or ""

    @property
    def type(self) -> str:
        """Return the device type of the Salus device list in lower case."""
        return (self.info.get("type") or "").lower()

    @property
    def category(self) -> str | None:
        """Return the Salus category id from the device list, or the one the Salus app gives the model."""
        category = self.info.get("category")
        if isinstance(category, dict) and category.get("category_id"):
            return str(category["category_id"])
        return MODEL_CATEGORIES.get(_MODEL_KEY.sub("_", self.model))

    @property
    def is_thermostat(self) -> bool:
        """Return whether the device is a thermostat (a relay the user named "Thermostat ..." is not)."""
        if (category := self.category) in THERMOSTAT_CATEGORIES:
            return True
        return (
            category not in OTHER_CATEGORIES
            and not self.is_switch
            and (
                self.type in ("thermostat", "climate")
                or self.model.upper().startswith(THERMOSTAT_MODELS)
                or "thermostat" in self.name.lower()
            )
        )

    @property
    def is_switch(self) -> bool:
        """Return whether the device is a relay or a smart plug."""
        return (
            self.category in SWITCH_CATEGORIES
            or self.type in ("switch", "relay")
            or self.model.upper().startswith(SWITCH_MODELS)
        )

    @property
    def is_binary_sensor(self) -> bool:
        """Return whether the device is a door, window, water leak, smoke or motion sensor."""
        return (
            self.category in BINARY_SENSOR_CATEGORIES
            or self.type in BINARY_SENSOR_TYPES
            or self.model.upper().startswith("WLS")
            or (
                not self.is_thermostat
                and not self.is_switch
                and find_property(self.properties, IAS_ZONE_ALARM_PATTERN) is not None
            )
        )

    @property
    def on_off_properties(self) -> list[str]:
        """Return the reported relay outputs, lowest endpoint first (an RS600 used as two relays has ep2 and ep3)."""
        return sorted(find_properties(self.properties, ON_OFF_PATTERN), key=endpoint_number)

    @property
    def cover_property(self) -> str | None:
        """Return the position property of a roller shutter, None for other devices and an RS600 used as relays."""
        if self.category != "30" or (key := find_property(self.properties, LEVEL_PATTERN)) is None:
            return None
        return None if self.properties.get(f"{endpoint(key)}:sButtonS:Mode") in RELAY_OUTPUT_MODES else key

    @property
    def humidity_read_command(self) -> str | None:
        """Return the command making the device measure and report its humidity now, None without humidity cluster.

        Thermostats report humidity on their own only after a large change: an IT800TX kept one value for 16 hours.
        """
        key = find_property(self.properties, HUMIDITY_CLUSTER_PATTERN)
        return None if key is None else f"{endpoint(key)}:sHumiS:SetReadMeasuredValue"

    @property
    def refresh_command(self) -> str | None:
        """Return the command making the device report all its properties again, as the Salus app sends it."""
        key = find_property(self.properties, ZDO_PATTERN)
        return None if key is None else f"{endpoint(key)}:sZDO:SetRefresh_d"
