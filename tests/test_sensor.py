"""Tests for separate thermostat sensors derived from shadow properties."""

from typing import Any
from unittest.mock import MagicMock

import pytest
from homeassistant.components.sensor import SensorDeviceClass

from custom_components.salus_cloud import binary_sensor, sensor
from custom_components.salus_cloud.binary_sensor import SalusHeatingBinarySensor
from custom_components.salus_cloud.sensor import SalusShadowSensor
from custom_components.salus_cloud.shadow import find_property, scaled_value
from custom_components.salus_cloud.thermostat import SHADOW_SENSORS

from . import fixtures
from .helpers import FakeApi, create_coordinator

PREFIX = f"salus_cloud_{fixtures.GATEWAY_ID}_{fixtures.THERMOSTAT_ID}"


async def _setup(platform: Any, api: FakeApi) -> list[Any]:
    coordinator, _, _ = await create_coordinator(api)
    entry = MagicMock()
    entry.runtime_data = coordinator
    add_entities = MagicMock()
    await platform.async_setup_entry(MagicMock(), entry, add_entities)
    return add_entities.call_args.args[0]


def _by_suffix(entities: list[Any], cls: type) -> dict[str, Any]:
    return {
        entity.unique_id.removeprefix(PREFIX + "_"): entity
        for entity in entities
        if isinstance(entity, cls) and entity.unique_id.startswith(PREFIX + "_")
    }


def _it800_shadow(**extra: int) -> dict[str, Any]:
    shadow = fixtures.it800_thermostat_shadow(hold_type=2, temperature_x100=2012, setpoint_x100=1700)
    shadow["state"]["reported"]["11"]["properties"].update(extra)
    return shadow


async def test_it800_thermostat_gets_separate_sensors() -> None:
    """Every reported iT800 value becomes its own sensor, converted to real units."""

    api = FakeApi()
    api.shadows[fixtures.THERMOSTAT_CODE] = _it800_shadow(**{"ep1:sHumiS:MeasuredValue_x100": 5712})
    sensors = _by_suffix(await _setup(sensor, api), SalusShadowSensor)

    assert set(sensors) == {
        "current_temperature",
        "target_temperature",
        "current_humidity",
        "battery_voltage",
        "preset",
        "system_mode",
    }
    values = {key: entity.native_value for key, entity in sensors.items()}
    assert values == {
        "current_temperature": 20.12,
        "target_temperature": 17.0,
        "current_humidity": 57.12,
        "battery_voltage": 2.8,
        "preset": "manual",
        "system_mode": "heat",
    }
    assert sensors["current_humidity"].device_class == SensorDeviceClass.HUMIDITY
    assert sensors["current_humidity"].extra_state_attributes == {"shadow_property": "ep1:sHumiS:MeasuredValue_x100"}
    # Short names under the device ("Temperature"), translated through the translation key
    temperature = sensors["current_temperature"]
    assert temperature.has_entity_name and temperature.translation_key == "current_temperature"
    assert "_attr_name" not in vars(temperature)


async def test_it600_thermostat_sensors_and_battery_scale() -> None:
    """iT600 reports BatteryVoltage in tenths of a volt without a suffix; no humidity means no humidity sensor."""

    sensors = _by_suffix(await _setup(sensor, FakeApi()), SalusShadowSensor)

    assert "current_humidity" not in sensors
    assert sensors["battery_voltage"].native_value == 3.0
    assert sensors["current_temperature"].native_value == 22.0
    assert sensors["preset"].native_value == "schedule"


async def test_relays_get_no_shadow_sensors() -> None:
    """Relays only report on/off, which is a switch, not a sensor."""

    entities = await _setup(sensor, FakeApi())
    relay_ids = [entity.unique_id for entity in entities if fixtures.RELAY_ID in entity.unique_id]
    assert relay_ids == []


async def test_heating_binary_sensor() -> None:
    """RunningState becomes a heat binary sensor for both families."""

    api = FakeApi()
    shadow = _it800_shadow()
    shadow["state"]["reported"]["11"]["properties"]["ep1:sTherS:RunningState"] = 1
    api.shadows[fixtures.THERMOSTAT_CODE] = shadow
    heating = _by_suffix(await _setup(binary_sensor, api), SalusHeatingBinarySensor)

    assert heating["heating"].is_on is True
    assert heating["heating"].has_entity_name and heating["heating"].translation_key == "heating"


@pytest.mark.parametrize(
    ("key", "matches"),
    [
        ("ep1:sHumiS:MeasuredValue_x100", True),
        ("ep9:sHumiS:MeasuredValue_x100", True),
        ("ep1:sTempS:MeasuredValue_x100", False),
        ("ep0:sIRTH:LocalHumidity_x100", True),
        ("ep9:sIT600TH:LocalHumidity_x100", True),
        ("ep1:sTherS:MeasuredRelativeHumidity_x100", True),
        ("ep1:sHumS:Humidity", True),
        ("ep1:sTherS:HumiditySetpoint_x100", False),
        ("ep1:sTherS:SetHumidity_x100", False),
        ("ep1:sHumiS:SetReadMeasuredValue", False),
        ("ep1:sComm:HumidityDisplay", False),
        ("ep1:sTherS:LocalTemperature_x100", False),
    ],
)
def test_humidity_pattern(key: str, matches: bool) -> None:
    """Humidity is recognised by name on any endpoint, setpoints and commands are not readings."""

    pattern = next(description.pattern for description in SHADOW_SENSORS if description.key == "current_humidity")
    assert (find_property({key: 1}, pattern) == key) is matches


def test_scaled_value() -> None:
    """Values are scaled by their _x100 / _x10 suffix and booleans are not numbers."""

    assert scaled_value("ep1:sTherS:LocalTemperature_x100", 2150) == 21.5
    assert scaled_value("ep1:sPowerS:BatteryVoltage_x10", 29) == 2.9
    assert scaled_value("ep1:sX:Value", 7) == 7.0
    assert scaled_value("ep1:sX:Value", True) is None


async def test_climate_reports_humidity() -> None:
    """The thermostat card shows humidity when the device reports it."""

    from custom_components.salus_cloud.climate import SalusCloudClimate

    api = FakeApi()
    api.shadows[fixtures.THERMOSTAT_CODE] = _it800_shadow(**{"ep1:sHumiS:MeasuredValue_x100": 5100})
    coordinator, _, _ = await create_coordinator(api)
    entity = SalusCloudClimate(coordinator, coordinator.data[fixtures.THERMOSTAT_ID])
    other = SalusCloudClimate(coordinator, coordinator.data[fixtures.THERMOSTAT_2_ID])

    assert entity.current_humidity == 51.0
    assert other.current_humidity is None


async def test_diagnostics_show_shadow_properties_without_identifiers() -> None:
    """Diagnostics expose raw property names and values but no credentials or device codes."""

    from custom_components.salus_cloud.diagnostics import async_get_config_entry_diagnostics

    api = FakeApi()
    api.shadows[fixtures.THERMOSTAT_CODE] = _it800_shadow()
    coordinator, _, _ = await create_coordinator(api)
    entry = MagicMock()
    entry.runtime_data = coordinator
    entry.data = {"email": "me@example.com", "password": "secret"}
    entry.options = {}

    result = await async_get_config_entry_diagnostics(MagicMock(), entry)

    assert result["entry"] == {"email": "**REDACTED**", "password": "**REDACTED**"}
    it800 = next(device for device in result["devices"] if device["property_family"] == "iT800")
    assert it800["shadow_properties"]["ep1:sTherS:LocalTemperature_x100"] == 2012
    text = repr(result)
    assert fixtures.THERMOSTAT_CODE not in text and "secret" not in text and "me@example.com" not in text


@pytest.mark.parametrize(("raw", "expected"), [(45, 45.0), (4512, 45.12)])
async def test_sq610_humidity_from_sunny_setpoint(raw: int, expected: float) -> None:
    """SQ610 thermostats report humidity in SunnySetpoint_x100, plain percent or x100."""

    from custom_components.salus_cloud.climate import SalusCloudClimate

    api = FakeApi()
    shadow = fixtures.thermostat_shadow(hold_type=0)
    shadow["state"]["reported"]["11"]["properties"]["ep9:sIT600TH:SunnySetpoint_x100"] = raw
    api.shadows[fixtures.THERMOSTAT_CODE] = shadow
    sensors = _by_suffix(await _setup(sensor, api), SalusShadowSensor)
    coordinator, _, _ = await create_coordinator(api)
    climate = SalusCloudClimate(coordinator, coordinator.data[fixtures.THERMOSTAT_ID])

    assert sensors["current_humidity"].native_value == expected
    assert climate.current_humidity == expected


async def test_sunny_setpoint_is_not_humidity_on_other_models() -> None:
    """Only SQ610 models use SunnySetpoint for humidity."""

    from custom_components.salus_cloud.thermostat import humidity_property

    assert humidity_property("TS600", {"ep9:sIT600TH:SunnySetpoint_x100": 2100}) is None
    assert humidity_property("SQ610RF", {"ep9:sIT600TH:SunnySetpoint_x100": 45}) == "ep9:sIT600TH:SunnySetpoint_x100"


def test_every_entity_has_translated_name_and_states() -> None:
    """Every sensor and the heating binary sensor have English names, and enum states have labels."""

    import json
    from pathlib import Path

    base = Path(__file__).parent.parent / "custom_components" / "salus_cloud"
    for path in (base / "strings.json", *sorted((base / "translations").glob("*.json"))):
        entity = json.loads(path.read_text(encoding="utf-8"))["entity"]
        for description in SHADOW_SENSORS:
            translated = entity["sensor"][description.key]
            assert translated["name"], (path.name, description.key)
            for option in description.options or []:
                assert translated["state"][option], (path.name, description.key, option)
        assert set(entity["binary_sensor"]["heating"]["state"]) == {"on", "off"}
        presets = entity["climate"]["thermostat"]["state_attributes"]["preset_mode"]["state"]
        assert set(presets) == {"schedule", "manual", "away"}, path.name
