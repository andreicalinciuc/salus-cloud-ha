"""A real IT800TX shadow (identifiers replaced), so entities follow the property names the device reports."""

import json
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.salus_cloud.const import CONF_HUMIDITY_INTERVAL, CONF_SYNC_MODES, DOMAIN
from custom_components.salus_cloud.coordinator import SalusCloudCoordinator
from custom_components.salus_cloud.diagnostics import async_get_config_entry_diagnostics

from . import fixtures
from .helpers import FakeApi, FakeConnection

REAL_PROPERTIES = json.loads((Path(__file__).parent / "real_it800tx.json").read_text())
PREFIX = f"{DOMAIN}_{fixtures.GATEWAY_ID}_{fixtures.THERMOSTAT_ID}"


class _Api(FakeApi):
    async def authenticate(self) -> None:
        return None


@contextmanager
def _patched(connection: FakeConnection) -> Iterator[None]:
    """Let the integration set up (and reload) with fixture data instead of Salus Cloud."""
    api = _Api()
    shadow = fixtures.it800_thermostat_shadow(hold_type=2)
    shadow["state"]["reported"]["11"]["properties"] = dict(REAL_PROPERTIES)
    api.shadows[fixtures.THERMOSTAT_CODE] = shadow

    def coordinator(hass: HomeAssistant, entry: Any, api: Any) -> SalusCloudCoordinator:
        return SalusCloudCoordinator(hass, entry, api, connection_factory=connection.factory)

    with (
        patch("custom_components.salus_cloud.SalusCloudApi", return_value=api),
        patch("custom_components.salus_cloud.SalusCloudCoordinator", side_effect=coordinator),
    ):
        yield


async def _set_up(hass: HomeAssistant, options: dict[str, Any]) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN, data={"email": "a@example.com", "password": "x"}, unique_id="a@example.com", options=options
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


@pytest.fixture
async def setup(hass: HomeAssistant, enable_custom: None) -> AsyncIterator[tuple[MockConfigEntry, FakeConnection]]:
    connection = FakeConnection()
    with _patched(connection):
        yield await _set_up(hass, {}), connection


def _entity_id(hass: HomeAssistant, platform: str, key: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(platform, DOMAIN, f"{PREFIX}_{key}")
    assert entity_id, key
    return entity_id


async def test_every_app_setting_gets_an_entity(
    hass: HomeAssistant, setup: tuple[MockConfigEntry, FakeConnection]
) -> None:
    """Each setting of the Salus app the IT800TX reports is shown, with the value it reports."""
    expected = {
        ("switch", "key_lock"): "off",
        ("switch", "display_always_on"): "off",
        ("switch", "optimum_start"): "off",
        ("switch", "optimum_stop"): "off",
        ("switch", "frost_protection"): "on",
        ("select", "display_brightness"): "high",
        ("select", "temperature_display_resolution"): "half_degree",
        ("select", "heating_control"): "tpi_underfloor",
        ("number", "temperature_calibration"): "0.0",
        ("number", "frost_temperature"): "5.0",
        ("number", "min_heat_setpoint"): "5.0",
        ("number", "max_heat_setpoint"): "35.0",
        ("sensor", "current_temperature"): "19.5",
        ("sensor", "current_humidity"): "57.48",
        ("sensor", "battery_voltage"): "3.9",
    }
    states = {key: hass.states.get(_entity_id(hass, *key)).state for key in expected}
    assert states == expected


async def test_display_resolution_is_written_with_the_reported_name(
    hass: HomeAssistant, setup: tuple[MockConfigEntry, FakeConnection]
) -> None:
    """The IT800TX reports TempDisplayResolution_x10, so the command is SetTempDisplayResolution_x10."""
    _, connection = setup
    with patch("custom_components.salus_cloud.coordinator.async_call_later"):
        await hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": _entity_id(hass, "select", "temperature_display_resolution"), "option": "tenth_degree"},
            blocking=True,
        )
    assert connection.published[-1][2] == {"ep1:sComm:SetTempDisplayResolution_x10": 1}


async def test_diagnostics_hide_pin_and_hardware_address(
    hass: HomeAssistant, setup: tuple[MockConfigEntry, FakeConnection]
) -> None:
    """The thermostat reports its key lock PIN; diagnostics must not show it."""
    entry, _ = setup
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    thermostat = next(device for device in diagnostics["devices"] if device["model"] == "SQ610RF")
    properties = thermostat["shadow_properties"]
    assert properties["ep1:sComm:PINLockCode"] == "**REDACTED**"
    assert properties["ep1:sZDO:EUID"] == "**REDACTED**"
    assert properties["ep1:sTherS:LocalTemperature_x100"] == 1950


READ_HUMIDITY = {"ep1:sHumiS:SetReadMeasuredValue": 1}


def _reads(connection: FakeConnection) -> int:
    return sum(properties == READ_HUMIDITY for _, _, properties in connection.published)


async def test_humidity_is_read_every_five_minutes(
    hass: HomeAssistant, setup: tuple[MockConfigEntry, FakeConnection]
) -> None:
    """The IT800TX keeps one humidity value for hours unless asked; by default it is asked every 5 minutes."""
    _, connection = setup
    assert _reads(connection) == 0
    for minutes in (5, 10):
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=minutes))
        await hass.async_block_till_done()
    assert _reads(connection) == 2


async def test_humidity_reads_can_be_turned_off(hass: HomeAssistant, enable_custom: None) -> None:
    """With the option at 0 the integration only shows what the device reports on its own."""
    connection = FakeConnection()
    with _patched(connection):
        await _set_up(hass, {CONF_HUMIDITY_INTERVAL: 0})
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=30))
        await hass.async_block_till_done()
    assert _reads(connection) == 0


async def test_options_set_the_humidity_interval(
    hass: HomeAssistant, setup: tuple[MockConfigEntry, FakeConnection]
) -> None:
    """The options form stores whole minutes and the reloaded integration uses them."""
    entry, _ = setup
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        flow["flow_id"], {CONF_SYNC_MODES: False, CONF_HUMIDITY_INTERVAL: 15.0}
    )
    await hass.async_block_till_done()
    assert result["type"] == "create_entry"
    assert entry.options == {CONF_SYNC_MODES: False, CONF_HUMIDITY_INTERVAL: 15}
    assert entry.runtime_data.humidity_interval == 15


async def test_refresh_button_asks_for_all_values(
    hass: HomeAssistant, setup: tuple[MockConfigEntry, FakeConnection]
) -> None:
    """Pressing Refresh sends the command the Salus app uses to have the device report everything again."""
    _, connection = setup
    with patch("custom_components.salus_cloud.coordinator.async_call_later"):
        await hass.services.async_call(
            "button", "press", {"entity_id": _entity_id(hass, "button", "refresh")}, blocking=True
        )
    assert connection.published[-1][2] == {"ep1:sZDO:SetRefresh_d": 1}
