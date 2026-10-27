"""Readings requested from devices: humidity every few minutes and a full refresh on demand."""

import json
import logging
from pathlib import Path
from unittest.mock import patch

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.salus_cloud.const import DEFAULT_SHADOW_INDEX

from . import fixtures
from .helpers import CALL_LATER, FakeApi, FakeConnection, create_coordinator
from .test_real_it800tx import REAL_PROPERTIES

READ_HUMIDITY = "ep1:sHumiS:SetReadMeasuredValue"
REFRESH = "ep1:sZDO:SetRefresh_d"


def _api() -> FakeApi:
    """Thermostat 1 is a real IT800TX, thermostat 2 an iT600 without humidity."""
    api = FakeApi()
    shadow = fixtures.it800_thermostat_shadow(hold_type=2)
    shadow["state"]["reported"]["11"]["properties"] = dict(REAL_PROPERTIES)
    api.shadows[fixtures.THERMOSTAT_CODE] = shadow
    return api


async def test_humidity_is_read_from_devices_with_a_humidity_cluster() -> None:
    """Only devices reporting sHumiS get the read command, on their own endpoint, without pending state."""
    coordinator, connection, _ = await create_coordinator(_api())

    await coordinator.async_read_humidity()

    assert connection.published == [(fixtures.THERMOSTAT_CODE, DEFAULT_SHADOW_INDEX, {READ_HUMIDITY: 1})]
    assert "ep1:sHumiS:ReadMeasuredValue" not in coordinator.data[fixtures.THERMOSTAT_ID].properties


async def test_failing_humidity_reads_are_logged_once(caplog: pytest.LogCaptureFixture) -> None:
    """An offline gateway gives one warning, not one every few minutes, and a note when reads work again."""
    caplog.set_level(logging.INFO)
    connection = FakeConnection(fail_codes={fixtures.THERMOSTAT_CODE})
    coordinator, _, _ = await create_coordinator(_api(), connection=connection)

    await coordinator.async_read_humidity()
    await coordinator.async_read_humidity()
    connection.fail_codes.clear()
    await coordinator.async_read_humidity()

    messages = [record.getMessage() for record in caplog.records if "humidity" in record.getMessage().lower()]
    assert len(messages) == 2
    assert "Living room thermostat" in messages[0]


async def test_refresh_asks_the_device_for_all_properties() -> None:
    """The refresh command goes to the endpoint the device reports its ZDO properties on."""
    coordinator, connection, _ = await create_coordinator(_api())

    with patch(CALL_LATER) as confirm:
        await coordinator.async_refresh_device(fixtures.THERMOSTAT_ID)

    confirm.assert_called_once()  # without pushed changes, a poll picks up what the device reports
    assert connection.published == [(fixtures.THERMOSTAT_CODE, DEFAULT_SHADOW_INDEX, {REFRESH: 1})]


async def test_failed_refresh_is_a_translated_error() -> None:
    """Pressing Refresh while the device cannot be reached shows an error in the UI."""
    connection = FakeConnection(fail_codes={fixtures.THERMOSTAT_CODE})
    coordinator, _, _ = await create_coordinator(_api(), connection=connection)

    with pytest.raises(HomeAssistantError) as err:
        await coordinator.async_refresh_device(fixtures.THERMOSTAT_ID)
    assert err.value.translation_key == "command_not_accepted"


def test_every_language_translates_every_text() -> None:
    """Each translation has exactly the texts of strings.json (Romanian lacked the setup and options)."""

    def keys(data: dict, prefix: str = "") -> set[str]:
        found: set[str] = set()
        for key, value in data.items():
            found |= keys(value, f"{prefix}{key}.") if isinstance(value, dict) else {prefix + key}
        return found

    component = Path(__file__).parent.parent / "custom_components" / "salus_cloud"
    expected = keys(json.loads((component / "strings.json").read_text()))
    for path in (component / "translations").glob("*.json"):
        assert keys(json.loads(path.read_text())) == expected, path.name
