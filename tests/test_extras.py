"""Extra IT800TX entities (settings, alarms, limits) in a real Home Assistant instance."""

from typing import Any
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.salus_cloud.const import DOMAIN
from custom_components.salus_cloud.coordinator import SalusCloudCoordinator
from custom_components.salus_cloud.gateway import receiver_mode
from custom_components.salus_cloud.shadow import set_property, signed_byte
from custom_components.salus_cloud.thermostat import active_errors

from . import fixtures
from .helpers import FakeApi, FakeConnection

# Properties the Salus app reads for ep1 thermostats (values as an IT800TX would report them)
IT800_EXTRA = {
    "ep1:sHumiS:MeasuredValue_x100": 5700,
    "ep1:sTherS:FloorTemperature_x100": -32768,  # no floor probe connected
    "ep1:sTherS:MinHeatSetpoint_x100": 700,
    "ep1:sTherS:MaxHeatSetpoint_x100": 3000,
    "ep1:sTherS:TempCalibration_x10": 251,  # -0.5 °C, reported as an unsigned byte
    "ep1:sComm:FrostSetpoint_x100": 700,
    "ep1:sComm:MinFrostSetpoint_x100": 500,
    "ep1:sComm:MaxFrostSetpoint_x100": 1200,
    "ep1:sPowerS:ErrorPowerSLowBattery": 0,
    "ep1:sPowerS:ErrorBatteryAlarmState_d": "00",
    "ep1:sTherUIS:LockKey": 1,
    "ep1:sTherS:ErrorTherSTempSensor": 0,
    "ep1:sTherS:ErrorTherSTempSensorShort": 1,
    "ep1:sZDO:FirmwareVersion": "0D5B0208",
    "ep1:sBasicS:HardwareVersion": 2,
    # Settings of the Salus app (Settings / Advanced settings)
    "ep1:sComm:LEDBrightness": 204,
    "ep1:sComm:DisplayAlwaysOn": 0,
    "ep1:sComm:OptimizeStart": 0,
    "ep1:sComm:OptimizeStop": 1,
    "ep1:sComm:HolidayActive": 1,
    "ep1:sComm:TempDisplayResolution": 5,
    "ep1:sComm:HeatingControlAlgorithm": 17,
}

# Wi-Fi gateway as a SAWZ600GW reports it (index 1), plus a receiver relay some gateways report (index 2)
RECEIVER_SHADOW = {
    "state": {
        "reported": {
            "000000000001": {
                "properties": {
                    "ep0:sGateway:GatewaySoftwareVersion": "000170240719",
                    "ep0:sGateway:GatewayHardwareVersion": "2",
                    "ep0:sGateway:WiFiRSSI": -70,
                    "ep0:sAWSIoT:CloudStatus": 1,
                    "ep0:sGateway:NetworkSSID": "Home",
                    "ep0:sGateway:NetworkPassword": "secret",
                    "ep0:sGateway:NetworkWiFiIP": "192.168.1.20",
                    "ep0:sAWSIoT:CertARN": "arn:aws:iot:eu-central-1:000000000000:cert/abc",
                    "ep0:sGateway:deviceFullList": ["001E5E0000000B02"],
                }
            },
            "000000000002": {"properties": {"ep1:sComm:RelayStatus": 1, "ep1:sComm:PanelSwitchStatus": 0}},
        }
    }
}


class _Api(FakeApi):
    async def authenticate(self) -> None:
        return None


@pytest.fixture
async def setup(hass: HomeAssistant, enable_custom: None) -> tuple[MockConfigEntry, FakeConnection]:
    api = _Api()
    shadow = fixtures.it800_thermostat_shadow(hold_type=2, temperature_x100=1950, setpoint_x100=1700)
    shadow["state"]["reported"]["11"]["properties"].update(IT800_EXTRA)
    api.shadows[fixtures.THERMOSTAT_CODE] = shadow
    api.shadows[fixtures.GATEWAY_CODE] = RECEIVER_SHADOW
    connection = FakeConnection()

    def coordinator(hass: HomeAssistant, entry: Any, api: Any) -> SalusCloudCoordinator:
        return SalusCloudCoordinator(hass, entry, api, connection_factory=connection.factory)

    entry = MockConfigEntry(domain=DOMAIN, data={"email": "a@example.com", "password": "x"}, unique_id="a@example.com")
    entry.add_to_hass(hass)
    with (
        patch("custom_components.salus_cloud.SalusCloudApi", return_value=api),
        patch("custom_components.salus_cloud.SalusCloudCoordinator", side_effect=coordinator),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry, connection


def _entity_id(hass: HomeAssistant, platform: str, suffix: str) -> str:
    unique_id = f"{DOMAIN}_{fixtures.GATEWAY_ID}_{fixtures.THERMOSTAT_ID}{suffix}"
    entity_id = er.async_get(hass).async_get_entity_id(platform, DOMAIN, unique_id)
    assert entity_id, unique_id
    return entity_id


async def test_extra_entities(hass: HomeAssistant, setup: tuple[MockConfigEntry, FakeConnection]) -> None:
    """Every reported setting and alarm becomes an entity with the right value."""

    def state(platform: str, suffix: str) -> Any:
        return hass.states.get(_entity_id(hass, platform, suffix))

    assert state("sensor", "_floor_temperature").state == "unknown"  # 0x8000 = no probe
    assert state("number", "_temperature_calibration").state == "-0.5"
    frost = state("number", "_frost_temperature")
    assert frost.state == "7.0"
    assert (frost.attributes["min"], frost.attributes["max"], frost.attributes["step"]) == (5.0, 12.0, 0.5)
    assert state("binary_sensor", "_battery_low").state == "off"
    assert state("switch", "_key_lock").state == "on"  # iT800: a switch instead of a read-only sensor
    assert hass.states.get("binary_sensor.living_room_thermostat_key_lock") is None
    assert state("switch", "_display_always_on").state == "off"
    assert state("switch", "_optimum_start").state == "off"
    assert state("switch", "_optimum_stop").state == "on"
    assert state("switch", "_frost_protection").state == "on"
    assert state("select", "_display_brightness").state == "high"
    assert state("select", "_temperature_display_resolution").state == "half_degree"
    heating_control = state("select", "_heating_control")
    assert heating_control.state == "tpi_radiator"
    assert "hysteresis_0_25" in heating_control.attributes["options"]
    assert state("number", "_min_heat_setpoint").state == "7.0"
    assert state("number", "_max_heat_setpoint").state == "30.0"
    problem = state("binary_sensor", "_problem")
    assert problem.state == "on"
    assert problem.attributes["errors"] == ["ErrorTherSTempSensorShort"]
    climate = state("climate", "")
    assert (climate.attributes["min_temp"], climate.attributes["max_temp"]) == (7.0, 30.0)


async def test_device_shows_firmware(hass: HomeAssistant, setup: tuple[MockConfigEntry, FakeConnection]) -> None:
    """Firmware and hardware version reported by the thermostat appear on the device page."""

    entry, _ = setup
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    thermostat = next(device for device in devices if (DOMAIN, fixtures.THERMOSTAT_ID) in device.identifiers)
    assert (thermostat.sw_version, thermostat.hw_version) == ("0D5B0208", "2")


async def test_number_sends_set_command(hass: HomeAssistant, setup: tuple[MockConfigEntry, FakeConnection]) -> None:
    """Changing a setting publishes the Set* property the Salus app uses, scaled like the reported value."""

    _, connection = setup
    with patch("custom_components.salus_cloud.coordinator.async_call_later"):
        await hass.services.async_call(
            "number",
            "set_value",
            {"entity_id": _entity_id(hass, "number", "_temperature_calibration"), "value": 1.2},
            blocking=True,
        )
        await hass.services.async_call(
            "number",
            "set_value",
            {"entity_id": _entity_id(hass, "number", "_frost_temperature"), "value": 8.5},
            blocking=True,
        )
    published = [properties for _, _, properties in connection.published]
    assert published == [{"ep1:sTherS:SetTempCalibration_x10": 12}, {"ep1:sComm:SetFrostSetpoint_x100": 850}]
    assert hass.states.get(_entity_id(hass, "number", "_temperature_calibration")).state == "1.2"


async def test_settings_send_set_commands(
    hass: HomeAssistant, setup: tuple[MockConfigEntry, FakeConnection]
) -> None:
    """Switches and selects publish the values the Salus app sends."""

    _, connection = setup
    calls = [
        ("switch", "turn_off", "_key_lock", {}),
        ("switch", "turn_on", "_display_always_on", {}),
        ("switch", "turn_on", "_optimum_start", {}),
        ("switch", "turn_off", "_frost_protection", {}),
        ("select", "select_option", "_display_brightness", {"option": "low"}),
        ("select", "select_option", "_temperature_display_resolution", {"option": "tenth_degree"}),
        ("select", "select_option", "_heating_control", {"option": "tpi_underfloor"}),
        ("number", "set_value", "_max_heat_setpoint", {"value": 28}),
    ]
    with patch("custom_components.salus_cloud.coordinator.async_call_later"):
        for platform, service, suffix, data in calls:
            await hass.services.async_call(
                platform, service, {"entity_id": _entity_id(hass, platform, suffix), **data}, blocking=True
            )
    assert [properties for _, _, properties in connection.published] == [
        {"ep1:sTherUIS:SetLockKey": 0},
        {"ep1:sComm:SetDisplayAlwaysOn": 1},
        {"ep1:sComm:SetOptimizeStart": 1},
        {"ep1:sComm:SetHolidayActive": 0},
        {"ep1:sComm:SetLEDBrightness": 64},
        {"ep1:sComm:SetTempDisplayResolution": 1},
        {"ep1:sComm:SetHeatingControlAlgorithm": 16},
        {"ep1:sTherS:SetMaxHeatSetpoint_x100": 2800},
    ]
    assert hass.states.get(_entity_id(hass, "select", "_heating_control")).state == "tpi_underfloor"
    assert hass.states.get(_entity_id(hass, "switch", "_key_lock")).state == "off"


async def test_receiver_entities(hass: HomeAssistant, setup: tuple[MockConfigEntry, FakeConnection]) -> None:
    """The Wi-Fi receiver (gateway) shows its boiler relay, mode and firmware."""

    entry, _ = setup
    registry = er.async_get(hass)
    boiler = registry.async_get_entity_id("binary_sensor", DOMAIN, f"{DOMAIN}_{fixtures.GATEWAY_ID}_boiler")
    mode = registry.async_get_entity_id("sensor", DOMAIN, f"{DOMAIN}_{fixtures.GATEWAY_ID}_receiver_mode")
    assert boiler and mode
    assert hass.states.get(boiler).state == "on"
    assert hass.states.get(mode).state == "auto"
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    gateway = next(device for device in devices if (DOMAIN, fixtures.GATEWAY_ID) in device.identifiers)
    assert (gateway.sw_version, gateway.hw_version) == ("000170240719", "2")
    signal = registry.async_get_entity_id("sensor", DOMAIN, f"{DOMAIN}_{fixtures.GATEWAY_ID}_wifi_signal")
    cloud = registry.async_get_entity_id("binary_sensor", DOMAIN, f"{DOMAIN}_{fixtures.GATEWAY_ID}_cloud_connection")
    assert hass.states.get(signal).state == "-70"
    assert hass.states.get(cloud).state == "on"
    assert registry.async_get(boiler).device_id == gateway.id


async def test_diagnostics_hide_network_details(
    hass: HomeAssistant, setup: tuple[MockConfigEntry, FakeConnection]
) -> None:
    """Gateway properties appear in diagnostics without the Wi-Fi name."""

    from custom_components.salus_cloud.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    entry, _ = setup
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    properties = diagnostics["gateways"][0]["shadow_properties"]
    assert properties["ep1:sComm:RelayStatus"] == 1
    for key in (
        "ep0:sGateway:NetworkSSID",
        "ep0:sGateway:NetworkPassword",
        "ep0:sGateway:NetworkWiFiIP",
        "ep0:sAWSIoT:CertARN",
        "ep0:sGateway:deviceFullList",
    ):
        assert properties[key] == "**REDACTED**", key
    assert properties["ep0:sGateway:WiFiRSSI"] == -70


def test_receiver_mode_and_signed_byte() -> None:
    """Receiver mode bits and the unsigned calibration byte are decoded like the Salus app does."""

    assert [receiver_mode(value) for value in (0, 1, 2, 3, None)] == ["auto", "auto", "manual_on", "manual_off", None]
    assert [signed_byte(value) for value in (0, 25, 231, 251, 255)] == [0, 25, -25, -5, -1]


def test_helpers() -> None:
    """Command names and error flags are derived from the reported properties."""

    assert set_property("ep1:sTherS:TempCalibration_x10") == "ep1:sTherS:SetTempCalibration_x10"
    assert active_errors(
        {
            "ep1:sTherS:ErrorTherSTempSensor": 1,
            "ep1:sPowerS:ErrorPowerSLowBattery": 1,  # has its own sensor
            "ep1:sPowerS:ErrorBatteryAlarmState_d": "01",  # raw data, not a flag
            "ep1:sBindS:ErrorLossLinkStatus": 0,
        }
    ) == ["ErrorTherSTempSensor"]
