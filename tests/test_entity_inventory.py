"""Every entity the fixture account gets, with the ids users' automations and dashboards depend on."""

from typing import Any
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.salus_cloud.const import DOMAIN
from custom_components.salus_cloud.coordinator import SalusCloudCoordinator

from . import fixtures
from .helpers import FakeApi, FakeConnection
from .test_extras import IT800_EXTRA, RECEIVER_SHADOW

GW = fixtures.GATEWAY_ID
T1 = fixtures.THERMOSTAT_ID
T2 = fixtures.THERMOSTAT_2_ID
RELAY = fixtures.RELAY_ID

# (platform, unique id without domain, translation key, name when untranslated, entity category, device class).
# Entity ids are left out: Home Assistant derives them differently per version and keeps existing ones anyway.
EXPECTED = [
    ("binary_sensor", "GW_T1_battery_low", "battery_low", None, "diagnostic", "battery"),
    ("binary_sensor", "GW_T1_heating", "heating", None, None, None),
    ("binary_sensor", "GW_T1_problem", "problem", None, "diagnostic", "problem"),
    ("binary_sensor", "GW_T2_heating", "heating", None, None, None),
    ("binary_sensor", "GW_boiler", "boiler", None, None, None),
    ("binary_sensor", "GW_cloud_connection", "cloud_connection", None, "diagnostic", "connectivity"),
    ("button", "GW_T1_refresh", "refresh", None, None, None),
    ("button", "GW_onetouch_40000000-0000-4000-8000-000000000001", None, "Home Heating off (Stand-by)", None, None),
    ("climate", "GW_T1", "thermostat", None, None, None),
    ("climate", "GW_T2", "thermostat", None, None, None),
    ("number", "GW_T1_frost_temperature", "frost_temperature", None, "config", "temperature"),
    ("number", "GW_T1_max_heat_setpoint", "max_heat_setpoint", None, "config", "temperature"),
    ("number", "GW_T1_min_heat_setpoint", "min_heat_setpoint", None, "config", "temperature"),
    ("number", "GW_T1_temperature_calibration", "temperature_calibration", None, "config", "temperature"),
    ("select", "GW_T1_display_brightness", "display_brightness", None, "config", None),
    ("select", "GW_T1_heating_control", "heating_control", None, "config", None),
    ("select", "GW_T1_temperature_display_resolution", "temperature_display_resolution", None, "config", None),
    ("sensor", "GW_T1_battery_voltage", "battery_voltage", None, "diagnostic", "voltage"),
    ("sensor", "GW_T1_current_humidity", "current_humidity", None, None, "humidity"),
    ("sensor", "GW_T1_current_temperature", "current_temperature", None, None, "temperature"),
    ("sensor", "GW_T1_floor_temperature", "floor_temperature", None, None, "temperature"),
    ("sensor", "GW_T1_preset", "preset", None, None, "enum"),
    ("sensor", "GW_T1_system_mode", "system_mode", None, "diagnostic", "enum"),
    ("sensor", "GW_T1_target_temperature", "target_temperature", None, None, "temperature"),
    ("sensor", "GW_T2_battery_voltage", "battery_voltage", None, "diagnostic", "voltage"),
    ("sensor", "GW_T2_current_temperature", "current_temperature", None, None, "temperature"),
    ("sensor", "GW_T2_preset", "preset", None, None, "enum"),
    ("sensor", "GW_T2_system_mode", "system_mode", None, "diagnostic", "enum"),
    ("sensor", "GW_T2_target_temperature", "target_temperature", None, None, "temperature"),
    ("sensor", "GW_receiver_mode", "receiver_mode", None, None, "enum"),
    ("sensor", "GW_wifi_signal", "wifi_signal", None, "diagnostic", "signal_strength"),
    ("switch", "GW_RELAY", None, None, None, None),
    ("switch", "GW_T1_display_always_on", "display_always_on", None, "config", None),
    ("switch", "GW_T1_frost_protection", "frost_protection", None, "config", None),
    ("switch", "GW_T1_key_lock", "key_lock", None, None, None),
    ("switch", "GW_T1_optimum_start", "optimum_start", None, "config", None),
    ("switch", "GW_T1_optimum_stop", "optimum_stop", None, "config", None),
]


class _Api(FakeApi):
    async def authenticate(self) -> None:
        return None


@pytest.fixture
async def entry(hass: HomeAssistant, enable_custom: None) -> MockConfigEntry:
    api = _Api()
    shadow = fixtures.it800_thermostat_shadow(hold_type=2, temperature_x100=1950, setpoint_x100=1700)
    shadow["state"]["reported"]["11"]["properties"].update(IT800_EXTRA)
    api.shadows[fixtures.THERMOSTAT_CODE] = shadow
    api.shadows[fixtures.GATEWAY_CODE] = RECEIVER_SHADOW

    def coordinator(hass: HomeAssistant, entry: Any, api: Any) -> SalusCloudCoordinator:
        return SalusCloudCoordinator(hass, entry, api, connection_factory=FakeConnection().factory)

    entry = MockConfigEntry(domain=DOMAIN, data={"email": "a@example.com", "password": "x"}, unique_id="a@example.com")
    entry.add_to_hass(hass)
    with (
        patch("custom_components.salus_cloud.SalusCloudApi", return_value=api),
        patch("custom_components.salus_cloud.SalusCloudCoordinator", side_effect=coordinator),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


def _short(unique_id: str) -> str:
    for name, value in (("GW", GW), ("T1", T1), ("T2", T2), ("RELAY", RELAY)):
        unique_id = unique_id.replace(value, name)
    return unique_id.removeprefix(f"{DOMAIN}_")


def inventory(hass: HomeAssistant, entry: MockConfigEntry) -> list[tuple[Any, ...]]:
    """Return the identity of every entity of the entry, sorted by unique id."""
    return sorted(
        (
            item.domain,
            _short(item.unique_id),
            item.translation_key,
            item.original_name if item.translation_key is None else None,
            item.entity_category.value if item.entity_category else None,
            str(item.original_device_class) if item.original_device_class else None,
        )
        for item in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    )


async def test_entity_inventory(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Unique ids, translation keys, names, categories and device classes do not change."""
    assert inventory(hass, entry) == EXPECTED
