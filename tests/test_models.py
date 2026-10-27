"""Salus models beyond iT600 / IT800TX, with the shadow property names the Salus app uses for them.

None of these shadows comes from a real device yet: the names and values follow the Salus web app
(eu.premium.salusconnect.io), which maps each device category to its properties.
"""

from typing import Any
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.salus_cloud.api import SalusMetadata
from custom_components.salus_cloud.const import DOMAIN
from custom_components.salus_cloud.coordinator import SalusCloudCoordinator
from custom_components.salus_cloud.device import SalusDevice
from custom_components.salus_cloud.properties import IT600, IT800, detect_property_names

from . import fixtures
from .helpers import FakeApi, FakeConnection, metadata

GW = fixtures.GATEWAY_ID
CALL_LATER = "custom_components.salus_cloud.coordinator.async_call_later"

# id suffix, model, category id (None: the device list has none), name, reported properties
DEVICES: list[tuple[str, str, str | None, str, dict[str, Any]]] = [
    (
        "fc600",
        "FC600",
        "32",
        "Office fan coil",
        {
            "ep9:sTherS:LocalTemperature_x100": 2250,
            "ep9:sTherS:HeatingSetpoint_x100": 2100,
            "ep9:sTherS:CoolingSetpoint_x100": 2400,
            "ep9:sTherS:SystemMode": 4,
            "ep9:sTherS:RunningState": 33,
            "ep9:sComm:HoldType": 2,
            "ep9:sFanS:FanMode": 5,
            "ep9:sTherUIS:LockKey": 0,
        },
    ),
    (
        "trv3rf",
        "TRV3RF",
        None,
        "Bedroom TRV",
        {
            "ep1:sTherS:LocalTemperature_x100": 2050,
            "ep1:sTherS:HeatingSetpoint_x100": 2100,
            "ep1:sTherS:SystemMode": 4,
            "ep1:sTherS:RunningState": 1,
            "ep1:sComm:HoldType": 0,
            "ep1:sPowerS:BatteryVoltage_x10": 27,
        },
    ),
    (
        "blind",
        "RS600",
        "30",
        "Living room blind",
        {
            "ep1:sLevelS:CurrentLevel": 25,
            "ep1:sButtonS:Mode": 5,
            "ep2:sOnOffS:OnOff": 0,
            "ep3:sOnOffS:OnOff": 0,
        },
    ),
    (
        "lights",
        "RS600",
        "30",
        "Garden lights",
        {"ep1:sLevelS:CurrentLevel": 0, "ep1:sButtonS:Mode": 3, "ep2:sOnOffS:OnOff": 1, "ep3:sOnOffS:OnOff": 0},
    ),
    (
        "ps600",
        "PS600",
        "20",
        "Hall sensor",
        {"ep9:sTempS:MeasuredValue_x100": 2215, "ep9:sIASZS:ErrorIASZSLowBattery": 1},
    ),
    ("minitrv", "it600MINITRV", "10", "Kitchen radiator", {"ep6:sIT600I:RelayStatus": 1, "ep6:sIT600I:Mode": 0}),
    ("motion", "MS600", None, "Hall motion", {"ep1:sIASZS:ErrorIASZSAlarmed1": 1}),
    ("plug", "SP600", None, "Coffee plug", {"ep9:sOnOffS:OnOff": 1}),
    ("hotwater", "TS600HW", None, "Hot water", {"ep9:sIT600HW:RunningMode": 1, "ep9:sIT600HW:HoldType": 0}),
]


def _id(suffix: str) -> str:
    return f"90000000-0000-4000-8000-{suffix:0>12}"


def _code(suffix: str, model: str) -> str:
    return f"{fixtures.GATEWAY_CODE}-{model}-{suffix:0>16}"


class _Api(FakeApi):
    """Fixture account plus one device of each model above."""

    def __init__(self) -> None:
        super().__init__()
        for suffix, model, _, _, properties in DEVICES:
            self.shadows[_code(suffix, model)] = {
                "state": {"reported": {"11": {"properties": dict(properties), "model": model}}}
            }

    async def authenticate(self) -> None:
        return None

    async def fetch_metadata(self) -> SalusMetadata:
        result = metadata()
        for suffix, model, category, name, _ in DEVICES:
            device = {"id": _id(suffix), "device_code": _code(suffix, model), "name": name, "model": model}
            if category is not None:
                device["category"] = {"name": None, "category_id": category}
            result.devices.append({**device, "_gateway_id": GW})
        return result


@pytest.fixture
async def setup(hass: HomeAssistant, enable_custom: None) -> FakeConnection:
    connection = FakeConnection()

    def coordinator(hass: HomeAssistant, entry: Any, api: Any) -> SalusCloudCoordinator:
        return SalusCloudCoordinator(hass, entry, api, connection_factory=connection.factory)

    entry = MockConfigEntry(domain=DOMAIN, data={"email": "a@example.com", "password": "x"}, unique_id="a@example.com")
    entry.add_to_hass(hass)
    with (
        patch("custom_components.salus_cloud.SalusCloudApi", return_value=_Api()),
        patch("custom_components.salus_cloud.SalusCloudCoordinator", side_effect=coordinator),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return connection


def _entity_id(hass: HomeAssistant, platform: str, suffix: str, key: str = "") -> str | None:
    return er.async_get(hass).async_get_entity_id(platform, DOMAIN, f"{DOMAIN}_{GW}_{_id(suffix)}{key}")


def _state(hass: HomeAssistant, platform: str, suffix: str, key: str = "") -> Any:
    entity_id = _entity_id(hass, platform, suffix, key)
    assert entity_id is not None, f"no {platform} entity for {suffix}{key}"
    return hass.states.get(entity_id)


async def _call(hass: HomeAssistant, platform: str, service: str, entity_id: str | None, **data: Any) -> None:
    with patch(CALL_LATER):
        await hass.services.async_call(platform, service, {"entity_id": entity_id, **data}, blocking=True)


async def test_fan_coil_thermostat_reads_its_ep9_sthers_properties(hass: HomeAssistant, setup: FakeConnection) -> None:
    """An FC600 reports sTherS / sComm under ep9 instead of the sIT600TH names of other ep9 thermostats."""
    state = _state(hass, "climate", "fc600")
    assert state.state == "heat"
    assert state.attributes["current_temperature"] == 22.5
    assert state.attributes["temperature"] == 21.0
    assert state.attributes["hvac_action"] == "heating"  # RunningState 33: fan coil heating
    assert state.attributes["preset_mode"] == "manual"


async def test_fan_coil_commands_keep_its_system_mode(hass: HomeAssistant, setup: FakeConnection) -> None:
    """A temperature change does not switch a (possibly cooling) fan coil to heating; off is the hold type alone."""
    entity_id = _entity_id(hass, "climate", "fc600")
    await _call(hass, "climate", "set_temperature", entity_id, temperature=23)
    await _call(hass, "climate", "set_hvac_mode", entity_id, hvac_mode="off")

    assert [properties for _, _, properties in setup.published] == [
        {"ep9:sTherS:SetHeatingSetpoint_x100": 2300, "ep9:sComm:SetHoldType": 2},
        {"ep9:sComm:SetHoldType": 7},
    ]


async def test_trv3rf_is_a_thermostat_with_ep1_properties(hass: HomeAssistant, setup: FakeConnection) -> None:
    """A TRV3RF without a category in the device list is found by its model and read like an IT800TX."""
    state = _state(hass, "climate", "trv3rf")
    assert state.state == "heat"
    assert state.attributes["current_temperature"] == 20.5
    assert state.attributes["preset_mode"] == "schedule"
    assert _state(hass, "sensor", "trv3rf", "_battery_voltage").state == "2.7"

    await _call(hass, "climate", "set_temperature", _entity_id(hass, "climate", "trv3rf"), temperature=19.5)
    assert setup.published[-1][2] == {
        "ep1:sTherS:SetHeatingSetpoint_x100": 1950,
        "ep1:sComm:SetHoldType": 2,
        "ep1:sTherS:SetSystemMode": 4,
    }


async def test_roller_shutter(hass: HomeAssistant, setup: FakeConnection) -> None:
    """An RS600 in roller shutter mode is a cover moved with the level command of the Salus app."""
    state = _state(hass, "cover", "blind")
    assert state.state == "open"
    assert state.attributes["current_position"] == 25
    assert state.attributes["device_class"] == "shutter"
    # Its relays drive the motor: only the first output stays a switch, as before
    assert _entity_id(hass, "switch", "blind") is not None
    assert _entity_id(hass, "switch", "blind", "_relay_3") is None

    entity_id = _entity_id(hass, "cover", "blind")
    await _call(hass, "cover", "set_cover_position", entity_id, position=75)
    await _call(hass, "cover", "open_cover", entity_id)
    await _call(hass, "cover", "close_cover", entity_id)

    assert [properties for _, _, properties in setup.published] == [
        {"ep1:sLevelS:SetMoveToLevel": "4bFFFF"},
        {"ep1:sLevelS:SetMoveToLevel": "64FFFF"},
        {"ep1:sLevelS:SetMoveToLevel": "00FFFF"},
    ]


async def test_rs600_used_as_two_relays(hass: HomeAssistant, setup: FakeConnection) -> None:
    """An RS600 in two-relay mode gets no cover and one switch per output; the second is named after its endpoint."""
    assert _entity_id(hass, "cover", "lights") is None
    assert _state(hass, "switch", "lights").state == "on"
    second = _state(hass, "switch", "lights", "_relay_3")
    assert second.state == "off"
    assert second.attributes["friendly_name"] == "Garden lights Relay 3"

    await _call(hass, "switch", "turn_on", second.entity_id)
    await _call(hass, "switch", "turn_off", _entity_id(hass, "switch", "lights"))

    assert [properties for _, _, properties in setup.published] == [
        {"ep3:sOnOffS:SetOnOff": 1},
        {"ep2:sOnOffS:SetOnOff": 0},
    ]


async def test_remote_temperature_sensor(hass: HomeAssistant, setup: FakeConnection) -> None:
    """A PS600 shows the temperature and battery alarm it reports."""
    assert _state(hass, "sensor", "ps600", "_current_temperature").state == "22.15"
    assert _state(hass, "binary_sensor", "ps600", "_battery_low").state == "on"


async def test_trv_paired_to_a_thermostat_shows_its_relay(hass: HomeAssistant, setup: FakeConnection) -> None:
    """A TRV controlled by its thermostat (it600MINITRV) has no climate entity, only whether it heats."""
    assert _entity_id(hass, "climate", "minitrv") is None
    assert _state(hass, "binary_sensor", "minitrv", "_heating").state == "on"


async def test_motion_sensor_and_plug_found_by_model(hass: HomeAssistant, setup: FakeConnection) -> None:
    """Models without a category in the device list are classified with the Salus app's model catalog."""
    motion = _state(hass, "binary_sensor", "motion")
    assert motion.state == "on"
    assert motion.attributes["device_class"] == "motion"
    assert _state(hass, "switch", "plug").state == "on"


async def test_hot_water_timer_is_not_a_thermostat(hass: HomeAssistant, setup: FakeConnection) -> None:
    """A TS600HW is a hot water timer, not a TS600 thermostat, and is not supported yet."""
    entry_id = hass.config_entries.async_entries(DOMAIN)[0].entry_id
    entries = er.async_entries_for_config_entry(er.async_get(hass), entry_id)
    assert not [entry for entry in entries if _id("hotwater") in entry.unique_id]


def test_category_from_the_device_list_wins_over_the_model() -> None:
    """The device list's category decides; a relay of a known category is never taken for a thermostat."""

    def device(model: str, category: str | None = None, name: str = "Device") -> SalusDevice:
        info: dict[str, Any] = {"model": model, "name": name}
        if category is not None:
            info["category"] = {"name": None, "category_id": category}
        return SalusDevice(id="d", code="c", gateway_id="g", info=info)

    assert device("SQ605RF(WB)").is_thermostat
    assert device("SQ620BRF").is_thermostat
    assert device("IT710TX").is_thermostat
    assert device("SC824ZB").is_switch
    assert not device("SC824ZB", name="Thermostat relay").is_thermostat
    assert not device("TS600HW").is_thermostat
    assert device("NEW-MODEL", category="47").is_thermostat
    assert not device("NEW-MODEL", category="4", name="Thermostat relay").is_thermostat
    assert device("NEW-MODEL", category="23").is_binary_sensor
    # A category the integration does not know leaves the decision to the model, as before
    assert device("HTRP-RF(50)", category="999").is_thermostat
    assert not device("NEW-MODEL", category="999").is_thermostat


def test_property_families() -> None:
    """sTherS outside ep1 (FC600 on ep9) has its own names; sIT600TH and ep1 thermostats keep theirs."""
    fan_coil = detect_property_names({"ep9:sTherS:LocalTemperature_x100": 2000, "ep9:sComm:HoldType": 2})
    assert fan_coil.hold_type == "ep9:sComm:HoldType"
    assert fan_coil.set_heating_setpoint == "ep9:sTherS:SetHeatingSetpoint_x100"
    assert not fan_coil.setpoint_sets_heat_mode
    assert detect_property_names({"ep9:sIT600TH:HoldType": 0, "ep9:sTherS:SystemMode": 4}) is IT600
    assert detect_property_names({"ep1:sTherS:LocalTemperature_x100": 2000}) is IT800


async def test_humidity_sensors_are_not_woken_up_for_readings() -> None:
    """Only thermostats are asked for humidity readings; a battery sensor reports on its own."""
    from .helpers import create_coordinator

    api = FakeApi()
    thermostat = fixtures.it800_thermostat_shadow(hold_type=0)
    thermostat["state"]["reported"]["11"]["properties"]["ep1:sHumiS:MeasuredValue_x100"] = 5000
    api.shadows[fixtures.THERMOSTAT_CODE] = thermostat
    api.shadows[fixtures.RELAY_CODE] = {
        "state": {"reported": {"11": {"properties": {"ep1:sHumiS:MeasuredValue_x100": 4000}}}}
    }
    coordinator, connection, _ = await create_coordinator(api)

    await coordinator.async_read_humidity()

    assert [code for code, _, _ in connection.published] == [fixtures.THERMOSTAT_CODE]


async def test_fan_coil_switched_off_by_its_system_mode_is_turned_on_again() -> None:
    """Turning on a fan coil that reports system mode off also sets heating, or it would stay off."""
    from .helpers import create_coordinator

    api = FakeApi()
    api.shadows[fixtures.THERMOSTAT_CODE] = {
        "state": {"reported": {"11": {"properties": {**DEVICES[0][4], "ep9:sTherS:SystemMode": 0}}}}
    }
    coordinator, connection, _ = await create_coordinator(api)

    with patch(CALL_LATER):
        await coordinator.async_set_hvac_mode(fixtures.THERMOSTAT_ID, True)

    assert connection.published[-1][2] == {"ep9:sComm:SetHoldType": 0, "ep9:sTherS:SetSystemMode": 4}


def _inventory(hass: HomeAssistant) -> list[tuple[Any, ...]]:
    """Return the identity of every entity of the devices above, with the id suffix in place of the device id."""
    rows = []
    entry_id = hass.config_entries.async_entries(DOMAIN)[0].entry_id
    for item in er.async_entries_for_config_entry(er.async_get(hass), entry_id):
        for suffix, *_ in DEVICES:
            if _id(suffix) in item.unique_id:
                rows.append(
                    (
                        item.domain,
                        item.unique_id.removeprefix(f"{DOMAIN}_{GW}_").replace(_id(suffix), suffix),
                        item.translation_key,
                        item.entity_category.value if item.entity_category else None,
                        str(item.original_device_class) if item.original_device_class else None,
                    )
                )
    return sorted(rows)


# (platform, unique id without domain and gateway, translation key, entity category, device class)
EXPECTED = [
    ("binary_sensor", "fc600_heating", "heating", None, None),
    ("binary_sensor", "fc600_key_lock", "key_lock", "diagnostic", None),
    ("binary_sensor", "minitrv_heating", "heating", None, None),
    ("binary_sensor", "motion", None, None, "motion"),
    ("binary_sensor", "ps600_battery_low", "battery_low", "diagnostic", "battery"),
    ("binary_sensor", "trv3rf_heating", "heating", None, None),
    ("climate", "fc600", "thermostat", None, None),
    ("climate", "trv3rf", "thermostat", None, None),
    ("cover", "blind", None, None, "shutter"),
    ("sensor", "fc600_current_temperature", "current_temperature", None, "temperature"),
    ("sensor", "fc600_preset", "preset", None, "enum"),
    ("sensor", "fc600_system_mode", "system_mode", "diagnostic", "enum"),
    ("sensor", "fc600_target_temperature", "target_temperature", None, "temperature"),
    ("sensor", "ps600_current_temperature", "current_temperature", None, "temperature"),
    ("sensor", "trv3rf_battery_voltage", "battery_voltage", "diagnostic", "voltage"),
    ("sensor", "trv3rf_current_temperature", "current_temperature", None, "temperature"),
    ("sensor", "trv3rf_preset", "preset", None, "enum"),
    ("sensor", "trv3rf_system_mode", "system_mode", "diagnostic", "enum"),
    ("sensor", "trv3rf_target_temperature", "target_temperature", None, "temperature"),
    ("switch", "blind", None, None, None),
    ("switch", "lights", None, None, None),
    ("switch", "lights_relay_3", "relay", None, None),
    ("switch", "plug", None, None, None),
]


async def test_entity_inventory_of_the_new_models(hass: HomeAssistant, setup: FakeConnection) -> None:
    """Unique ids, translation keys, categories and device classes of the new models do not change."""
    assert _inventory(hass) == EXPECTED
