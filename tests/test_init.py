"""Set up the integration in a real Home Assistant instance and check what the user sees."""

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


class _Api(FakeApi):
    async def authenticate(self) -> None:
        return None


@pytest.fixture
async def setup_it800(hass: HomeAssistant, enable_custom: None) -> MockConfigEntry:
    api = _Api()
    shadow = fixtures.it800_thermostat_shadow(hold_type=2, temperature_x100=1950, setpoint_x100=1700)
    shadow["state"]["reported"]["11"]["properties"]["ep1:sHumiS:MeasuredValue_x100"] = 5700
    api.shadows[fixtures.THERMOSTAT_CODE] = shadow
    connection = FakeConnection()

    def coordinator(hass: HomeAssistant, entry: Any, api: Any) -> SalusCloudCoordinator:
        return SalusCloudCoordinator(hass, entry, api, connection_factory=connection.factory)

    entry = MockConfigEntry(
        domain=DOMAIN, data={"email": "me@example.com", "password": "x"}, unique_id="me@example.com"
    )
    entry.add_to_hass(hass)
    with (
        patch("custom_components.salus_cloud.SalusCloudApi", return_value=api),
        patch("custom_components.salus_cloud.SalusCloudCoordinator", side_effect=coordinator),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


def _state_by_unique_id(hass: HomeAssistant, platform: str, suffix: str) -> Any:
    registry = er.async_get(hass)
    unique_id = f"{DOMAIN}_{fixtures.GATEWAY_ID}_{fixtures.THERMOSTAT_ID}{suffix}"
    entity_id = registry.async_get_entity_id(platform, DOMAIN, unique_id)
    assert entity_id, unique_id
    return hass.states.get(entity_id)


async def test_entities_have_short_names_and_readable_states(hass: HomeAssistant, setup_it800: MockConfigEntry) -> None:
    """Names are "<device> <value>" (the device page shows just the value name) and states are labels."""

    climate = _state_by_unique_id(hass, "climate", "")
    humidity = _state_by_unique_id(hass, "sensor", "_current_humidity")
    preset = _state_by_unique_id(hass, "sensor", "_preset")
    heating = _state_by_unique_id(hass, "binary_sensor", "_heating")

    assert climate.attributes["friendly_name"] == "Living room thermostat"
    assert climate.attributes["current_humidity"] == 57.0
    assert humidity.attributes["friendly_name"] == "Living room thermostat Humidity"
    assert humidity.state == "57.0"
    assert preset.attributes["friendly_name"] == "Living room thermostat Preset"
    assert preset.state == "manual"
    assert preset.attributes["options"] == ["schedule", "manual", "frost_protection"]
    assert heating.attributes["friendly_name"] == "Living room thermostat Heating"
    assert heating.state == "off"


async def test_devices_are_linked_to_their_gateway(hass: HomeAssistant, setup_it800: MockConfigEntry) -> None:
    """Thermostats show "connected via" their gateway on every supported Home Assistant version."""

    from homeassistant.helpers import device_registry as dr

    devices = dr.async_entries_for_config_entry(dr.async_get(hass), setup_it800.entry_id)
    gateway = next(device for device in devices if (DOMAIN, fixtures.GATEWAY_ID) in device.identifiers)
    thermostat = next(device for device in devices if (DOMAIN, fixtures.THERMOSTAT_ID) in device.identifiers)
    assert thermostat.via_device_id == gateway.id
