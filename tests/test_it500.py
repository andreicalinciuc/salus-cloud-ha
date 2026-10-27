"""Salus iT500 accounts set up in a real Home Assistant instance: entities, commands and diagnostics.

None of the attributes come from a two zone or hot water iT500 yet; they follow the attribute descriptions of the API.
"""

import asyncio
from typing import Any
from unittest.mock import call, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.salus_cloud.api import SalusCloudConnectionError
from custom_components.salus_cloud.const import DOMAIN
from custom_components.salus_cloud.diagnostics import async_get_config_entry_diagnostics
from custom_components.salus_cloud.it500.api import It500Device

from . import it500_fixtures as fx

CALL_LATER = "custom_components.salus_cloud.it500.coordinator.async_call_later"
SINGLE = fx.DEVICE_ID
TWO_ZONES = "200000002"
HOT_WATER = "300000003"


class FakeIt500Api:
    """Salus iT500 account with a single zone, a two zone and a hot water thermostat."""

    def __init__(self) -> None:
        self.attributes: dict[str, dict[str, str]] = {
            SINGLE: dict(fx.SINGLE_ZONE),
            TWO_ZONES: {
                **fx.SINGLE_ZONE,
                "desc": "Upstairs",
                "S06": "1",
                "A89": "0",
                "A92": "0",
                "A88": "1",
                "B84": "1900",
                "B85": "2000",
                "B87": "1",
            },
            HOT_WATER: {**fx.SINGLE_ZONE, "desc": "Cottage", "S06": "2", "A89": "0", "C42": "0", "C45": "1"},
        }
        self.writes: list[tuple[str, str, str]] = []
        self.fail_writes = False
        self.resets = 0

    async def authenticate(self) -> None:
        return None

    async def get_devices(self) -> list[It500Device]:
        return [It500Device(id=device_id, serial=fx.SERIAL, type_id="1") for device_id in self.attributes]

    async def get_attributes(self, device_id: str) -> dict[str, str]:
        return dict(self.attributes[device_id])

    async def set_attribute(self, device_id: str, name: str, value: str) -> None:
        if self.fail_writes:
            raise SalusCloudConnectionError("refused")
        self.writes.append((device_id, name, value))

    def reset_session(self) -> None:
        self.resets += 1


@pytest.fixture
def api() -> FakeIt500Api:
    return FakeIt500Api()


@pytest.fixture
async def entry(hass: HomeAssistant, enable_custom: None, api: FakeIt500Api) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"email": "me@example.com", "password": "x", "account_type": "it500"},
        unique_id="it500_me@example.com",
    )
    entry.add_to_hass(hass)
    with patch("custom_components.salus_cloud.it500.SalusIt500Api", return_value=api):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


def _entity_id(hass: HomeAssistant, platform: str, device_id: str, key: str = "") -> str:
    entity_id = er.async_get(hass).async_get_entity_id(platform, DOMAIN, f"{DOMAIN}_it500_{device_id}{key}")
    assert entity_id is not None, f"no {platform} entity for {device_id}{key}"
    return entity_id


def _state(hass: HomeAssistant, platform: str, device_id: str, key: str = "") -> Any:
    return hass.states.get(_entity_id(hass, platform, device_id, key))


async def _call(hass: HomeAssistant, platform: str, service: str, entity_id: str, **data: Any) -> None:
    with patch(CALL_LATER) as call_later:
        await hass.services.async_call(platform, service, {"entity_id": entity_id, **data}, blocking=True)
    assert call_later.called, "the values are read again shortly after a command"


def _inventory(hass: HomeAssistant, entry: MockConfigEntry) -> list[tuple[Any, ...]]:
    names = {SINGLE: "single", TWO_ZONES: "two_zones", HOT_WATER: "hot_water"}
    rows = []
    for item in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id):
        unique_id = item.unique_id.removeprefix(f"{DOMAIN}_it500_")
        device_id, _, key = unique_id.partition("_")
        rows.append(
            (
                item.domain,
                f"{names[device_id]}{'_' + key if key else ''}",
                item.translation_key,
                item.entity_category.value if item.entity_category else None,
                str(item.original_device_class) if item.original_device_class else None,
            )
        )
    return sorted(rows)


def _expected(name: str, *extra: tuple[Any, ...]) -> list[tuple[Any, ...]]:
    return [
        ("binary_sensor", f"{name}_battery_low", "battery_low", "diagnostic", "battery"),
        ("binary_sensor", f"{name}_cloud_connection", "cloud_connection", "diagnostic", "connectivity"),
        ("binary_sensor", f"{name}_frost_protection", "frost_protection", None, None),
        ("binary_sensor", f"{name}_heating", "heating", None, None),
        ("button", f"{name}_refresh", "refresh", None, None),
        ("climate", name, "thermostat", None, None),
        ("sensor", f"{name}_current_temperature", "current_temperature", None, "temperature"),
        ("sensor", f"{name}_signal_strength", "signal_strength", "diagnostic", "signal_strength"),
        ("sensor", f"{name}_target_temperature", "target_temperature", None, "temperature"),
        *extra,
    ]


async def test_entity_inventory(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """A second zone and hot water get entities only on systems that have them."""
    expected = [
        *_expected("single"),
        *_expected(
            "two_zones",
            ("binary_sensor", "two_zones_zone_2_frost_protection", "zone_2_frost_protection", None, None),
            ("binary_sensor", "two_zones_zone_2_heating", "zone_2_heating", None, None),
            ("climate", "two_zones_zone_2", "zone_2", None, None),
            ("sensor", "two_zones_zone_2_current_temperature", "zone_2_current_temperature", None, "temperature"),
            ("sensor", "two_zones_zone_2_target_temperature", "zone_2_target_temperature", None, "temperature"),
        ),
        *_expected(
            "hot_water",
            ("binary_sensor", "hot_water_hot_water", "hot_water", None, None),
            ("select", "hot_water_hot_water_mode", "hot_water_mode", None, None),
        ),
    ]
    assert _inventory(hass, entry) == sorted(expected)


async def test_states_of_a_real_single_zone_thermostat(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """The thermostat reported off and manual at once: it is off, and shown with its name from the app."""
    climate = _state(hass, "climate", SINGLE)
    assert climate.state == "off"
    assert climate.name == "Home"
    assert climate.attributes["current_temperature"] == 17.5
    assert climate.attributes["temperature"] == 12.1
    assert climate.attributes["preset_mode"] is None
    assert climate.attributes["hvac_action"] == "off"
    assert _state(hass, "sensor", SINGLE, "_current_temperature").state == "17.5"
    assert _state(hass, "binary_sensor", SINGLE, "_cloud_connection").state == "on"
    assert _state(hass, "binary_sensor", SINGLE, "_battery_low").state == "off"

    registry = dr.async_get(hass)
    device = next(
        item
        for item in dr.async_entries_for_config_entry(registry, entry.entry_id)
        if (DOMAIN, f"it500_{SINGLE}") in item.identifiers
    )
    assert (device.model, device.sw_version, device.serial_number) == ("iT500", "11.7", fx.SERIAL)


async def test_two_zones_and_hot_water(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    zone_1 = _state(hass, "climate", TWO_ZONES)
    assert (zone_1.state, zone_1.attributes["preset_mode"]) == ("heat", "temporary_hold")
    zone_2 = _state(hass, "climate", TWO_ZONES, "_zone_2")
    assert zone_2.name == "Upstairs Zone 2"
    assert (zone_2.state, zone_2.attributes["preset_mode"], zone_2.attributes["hvac_action"]) == (
        "heat",
        "schedule",
        "heating",
    )
    assert zone_2.attributes["current_temperature"] == 19.0
    assert _state(hass, "select", HOT_WATER, "_hot_water_mode").state == "auto"
    assert _state(hass, "binary_sensor", HOT_WATER, "_hot_water").state == "on"


async def test_commands_wake_the_thermostat_and_show_the_new_value(
    hass: HomeAssistant, entry: MockConfigEntry, api: FakeIt500Api
) -> None:
    """Each command first puts the thermostat in refresh mode, then writes one attribute per request."""
    climate = _entity_id(hass, "climate", SINGLE)
    await _call(hass, "climate", "set_temperature", climate, temperature=21.5)
    assert _state(hass, "climate", SINGLE).attributes["temperature"] == 21.5
    await _call(hass, "climate", "set_hvac_mode", climate, hvac_mode="heat")
    assert _state(hass, "climate", SINGLE).state == "heat"
    assert _state(hass, "climate", SINGLE).attributes["preset_mode"] == "manual"

    assert api.writes == [
        (SINGLE, "F", "60"),
        (SINGLE, "A85", "2150"),
        (SINGLE, "F", "60"),
        (SINGLE, "A89", "0"),
    ]


async def test_presets_and_zone_2(hass: HomeAssistant, entry: MockConfigEntry, api: FakeIt500Api) -> None:
    with (
        patch("custom_components.salus_cloud.it500.coordinator.REWRITE_DELAY_SECONDS", 0.0123),
        patch("asyncio.sleep", wraps=asyncio.sleep) as sleep,
    ):
        await _call(hass, "climate", "set_preset_mode", _entity_id(hass, "climate", TWO_ZONES), preset_mode="schedule")
    # Manual mode is taken before the manual flag is cleared again
    assert sleep.call_args_list.count(call(0.0123)) == 1
    await _call(hass, "climate", "set_temperature", _entity_id(hass, "climate", TWO_ZONES, "_zone_2"), temperature=18)
    await _call(hass, "climate", "turn_off", _entity_id(hass, "climate", TWO_ZONES, "_zone_2"))

    assert [(name, value) for _, name, value in api.writes if name != "F"] == [
        # A temporary hold ends through manual mode
        ("A92", "1"),
        ("A88", "0"),
        ("A92", "0"),
        ("B85", "1800"),
        ("B89", "1"),
    ]
    assert _state(hass, "climate", TWO_ZONES).attributes["preset_mode"] == "schedule"
    assert _state(hass, "climate", TWO_ZONES, "_zone_2").state == "off"


async def test_hot_water_mode_and_refresh(hass: HomeAssistant, entry: MockConfigEntry, api: FakeIt500Api) -> None:
    await _call(hass, "select", "select_option", _entity_id(hass, "select", HOT_WATER, "_hot_water_mode"), option="off")
    await _call(hass, "button", "press", _entity_id(hass, "button", HOT_WATER, "_refresh"))

    assert api.writes == [(HOT_WATER, "F", "60"), (HOT_WATER, "C42", "3"), (HOT_WATER, "F", "60")]
    assert _state(hass, "select", HOT_WATER, "_hot_water_mode").state == "off"


async def test_refused_command_is_reported(hass: HomeAssistant, entry: MockConfigEntry, api: FakeIt500Api) -> None:
    api.fail_writes = True
    with pytest.raises(HomeAssistantError) as error:
        await hass.services.async_call(
            "climate",
            "set_temperature",
            {"entity_id": _entity_id(hass, "climate", SINGLE), "temperature": 20},
            blocking=True,
        )
    assert error.value.translation_key == "command_not_accepted"
    assert _state(hass, "climate", SINGLE).attributes["temperature"] == 12.1


async def test_broken_session_reading_is_ignored(
    hass: HomeAssistant, entry: MockConfigEntry, api: FakeIt500Api
) -> None:
    """A 32 °C / 32 °C reading of a broken session is not shown and the next poll logs in again."""
    api.attributes[SINGLE].update({"A84": "3200", "A85": "3200"})
    await entry.runtime_data.async_refresh()

    assert _state(hass, "climate", SINGLE).attributes["current_temperature"] == 17.5
    assert api.resets == 1


async def test_no_options_and_unload(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Mode synchronization and humidity reading are Salus Cloud options; an iT500 account has none."""
    assert not entry.supports_options
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_diagnostics_hide_phone_numbers_and_location(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert diagnostics["entry"] == {"email": "**REDACTED**", "password": "**REDACTED**", "account_type": "it500"}
    attributes = diagnostics["devices"][0]["attributes"]
    assert attributes["Phone1"] == "**REDACTED**"
    assert attributes["Rule"] == "**REDACTED**"
    assert attributes["A84"] == "1750"
    assert fx.DEVICE_ID not in str(diagnostics)
