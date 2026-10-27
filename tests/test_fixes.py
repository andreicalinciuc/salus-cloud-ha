"""Regression tests for bugs fixed in 2.2.0."""

import asyncio
import time
from typing import Any
from unittest.mock import MagicMock

from homeassistant.components.binary_sensor import BinarySensorDeviceClass

from custom_components.salus_cloud import binary_sensor
from custom_components.salus_cloud.api import SalusMetadata
from custom_components.salus_cloud.climate import SalusCloudClimate
from custom_components.salus_cloud.device import SalusDevice

from . import fixtures
from .helpers import FakeApi, create_coordinator, metadata
from .test_api import _api

LEAK_ID = "70000000-0000-4000-8000-000000000001"
LEAK_CODE = "SAU2AG1_GW-001E5E000001-WLS600-001E5E0000000E05"
DOOR_ID = "70000000-0000-4000-8000-000000000002"
DOOR_CODE = "SAU2AG1_GW-001E5E000001-SW600-001E5E0000000F06"
ALARM = "ep9:sIASZS:ErrorIASZSAlarmed1"


def _sensor_shadow(model: str, alarmed: int) -> dict[str, Any]:
    return {"state": {"reported": {"11": {"properties": {ALARM: alarmed}, "model": model}}}}


class _ApiWithSensors(FakeApi):
    """Fixture account plus a water leak sensor and a door sensor."""

    def __init__(self) -> None:
        super().__init__()
        self.shadows[LEAK_CODE] = _sensor_shadow("WLS600", 1)
        self.shadows[DOOR_CODE] = _sensor_shadow("SW600", 0)

    async def fetch_metadata(self) -> SalusMetadata:
        result = metadata()
        for device_id, code, name, model in (
            (LEAK_ID, LEAK_CODE, "Kitchen leak", "WLS600"),
            (DOOR_ID, DOOR_CODE, "Front door", "SW600"),
        ):
            result.devices.append(
                {"id": device_id, "device_code": code, "name": name, "model": model, "_gateway_id": fixtures.GATEWAY_ID}
            )
        return result


async def _climate(temperature_x100: int) -> SalusCloudClimate:
    api = FakeApi()
    api.shadows[fixtures.THERMOSTAT_CODE] = fixtures.thermostat_shadow(hold_type=0, temperature_x100=temperature_x100)
    coordinator, _, _ = await create_coordinator(api)
    return SalusCloudClimate(coordinator, coordinator.data[fixtures.THERMOSTAT_ID])


async def test_missing_temperature_sensor_is_unknown_on_the_thermostat() -> None:
    """Zigbee reports a missing sensor as 0x8000; the thermostat must not show -327.68 °C."""
    assert (await _climate(-32768)).current_temperature is None
    assert (await _climate(2150)).current_temperature == 21.5


async def test_unexpected_battery_value_does_not_break_thermostat_attributes() -> None:
    """A non-numeric battery voltage is left out instead of failing every state update."""
    api = FakeApi()
    shadow = fixtures.thermostat_shadow(hold_type=0)
    shadow["state"]["reported"]["11"]["properties"]["ep9:sBasicS:BatteryVoltage"] = "n/a"
    api.shadows[fixtures.THERMOSTAT_CODE] = shadow
    coordinator, _, _ = await create_coordinator(api)

    attributes = SalusCloudClimate(coordinator, coordinator.data[fixtures.THERMOSTAT_ID]).extra_state_attributes

    assert "battery_voltage" not in attributes
    assert attributes["hold_type"] == "Schedule"


def test_relay_named_thermostat_is_not_a_thermostat() -> None:
    """A relay the user named "Thermostat ..." stays a relay instead of also getting a climate entity."""
    relay = SalusDevice(id="r", code="c", gateway_id="g", info={"model": "SR600", "name": "Thermostat relay"})
    assert relay.is_switch
    assert not relay.is_thermostat


async def test_concurrent_requests_log_in_once() -> None:
    """Polling and the MQTT credential renewal running at the same time share one login."""
    api, _, login = _api({"/occupants/slider_list": lambda: _response(fixtures.slider_list())})
    fast_login = api._sync_authenticate

    def slow_login() -> None:
        time.sleep(0.05)  # SRP login takes a moment; the others must wait instead of logging in too
        fast_login()

    api._sync_authenticate = slow_login

    await asyncio.gather(api.get_gateways(), api.get_gateways(), api.get_gateways())

    assert login.call_count == 1


async def test_no_devices_sends_no_shadow_request() -> None:
    """An account with only a gateway does not ask Salus Cloud for the shadows of no devices."""
    api, session, _ = _api({})

    assert await api.get_device_shadows([]) == {}
    assert session.requests == []


async def test_water_leak_and_door_sensors_read_their_shadow() -> None:
    """IAS zone sensors show the alarm they report; a WLS600 is a water leak sensor, not a door."""
    coordinator, _, _ = await create_coordinator(_ApiWithSensors())
    entry = MagicMock()
    entry.runtime_data = coordinator
    add_entities = MagicMock()

    await binary_sensor.async_setup_entry(MagicMock(), entry, add_entities)

    sensors = {entity.unique_id.rsplit("_", 1)[-1]: entity for entity in add_entities.call_args.args[0]}
    assert sensors[LEAK_ID].device_class == BinarySensorDeviceClass.MOISTURE
    assert sensors[LEAK_ID].is_on is True
    assert sensors[DOOR_ID].device_class == BinarySensorDeviceClass.DOOR
    assert sensors[DOOR_ID].is_on is False


def _response(payload: Any) -> Any:
    from .test_api import _Response

    return _Response(200, payload)


def test_non_numeric_device_list_value_is_unknown() -> None:
    """A device list field that is not a number gives an unknown sensor value instead of an error."""
    from custom_components.salus_cloud.sensor import _value

    assert _value({"battery": "low"}, ("battery",), False) is None
    assert _value({"status": {"humidity": 5512}}, ("humidity",), True) == 55.12


async def test_rejected_command_has_a_translated_error() -> None:
    """Errors shown in the UI are translated; every key the code raises has a message in each language."""
    import json
    import re
    from pathlib import Path

    import pytest
    from homeassistant.exceptions import HomeAssistantError

    from .helpers import FakeConnection

    coordinator, _, _ = await create_coordinator(connection=FakeConnection(fail_codes={fixtures.RELAY_CODE}))
    with pytest.raises(HomeAssistantError) as err:
        await coordinator.async_set_switch(fixtures.RELAY_ID, True)
    assert err.value.translation_key == "command_not_accepted"
    assert err.value.translation_placeholders == {"devices": "Living room heating"}

    component = Path(__file__).parent.parent / "custom_components" / "salus_cloud"
    raised = set(re.findall(r'_error\(\s*"(\w+)"', (component / "coordinator.py").read_text()))
    assert raised == {"device_not_found", "gateway_not_found", "command_not_accepted", "rule_trigger_failed"}
    for path in (component / "strings.json", *(component / "translations").glob("*.json")):
        assert set(json.loads(path.read_text())["exceptions"]) == raised, path.name


async def test_only_devices_gone_from_the_account_can_be_removed() -> None:
    """Home Assistant lets the user delete a device only once Salus Cloud no longer lists it."""
    from custom_components.salus_cloud import async_remove_config_entry_device
    from custom_components.salus_cloud.const import DOMAIN

    coordinator, _, _ = await create_coordinator()
    entry = MagicMock()
    entry.runtime_data = coordinator

    for identifier, expected in (
        (fixtures.THERMOSTAT_ID, False),
        (fixtures.GATEWAY_ID, False),
        (f"{fixtures.GATEWAY_ID}_onetouch_rules", False),
        ("80000000-0000-4000-8000-000000000009", True),
    ):
        device = MagicMock(identifiers={(DOMAIN, identifier)})
        assert await async_remove_config_entry_device(MagicMock(), entry, device) is expected, identifier


def test_thermostat_reporting_an_ias_zone_is_not_a_contact() -> None:
    """Only devices that are neither thermostat nor relay become contacts because of their IAS zone alarm."""
    properties = {ALARM: 0}
    thermostat = SalusDevice(id="t", code="c", gateway_id="g", info={"model": "IT800TX"}, properties=properties)
    contact = SalusDevice(id="d", code="c", gateway_id="g", info={"model": "SW600"}, properties=properties)
    assert not thermostat.is_binary_sensor
    assert contact.is_binary_sensor
