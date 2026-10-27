"""Setup: the user picks the app of the account (Salus Smart Home or Salus iT500), then logs in."""

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.salus_cloud.api import SalusCloudAuthenticationError
from custom_components.salus_cloud.const import DOMAIN
from custom_components.salus_cloud.it500.api import It500Device

CREDENTIALS = {"email": "Me@Example.com", "password": "secret"}


@pytest.fixture(autouse=True)
def no_setup() -> Any:
    with patch("custom_components.salus_cloud.async_setup_entry", return_value=True) as setup:
        yield setup


def _it500_api(devices: list[It500Device] | None = None, error: Exception | None = None) -> AsyncMock:
    api = AsyncMock()
    api.authenticate.side_effect = error
    api.get_devices.return_value = [It500Device(id="1", serial="STA1", type_id="1")] if devices is None else devices
    return api


async def _start(hass: HomeAssistant, account: str) -> dict[str, Any]:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == ["cloud", "it500"]
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": account})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == account
    return result


async def test_salus_smart_home_account(hass: HomeAssistant, enable_custom: None) -> None:
    api = AsyncMock()
    api.get_gateways.return_value = [object()]
    result = await _start(hass, "cloud")
    with patch("custom_components.salus_cloud.config_flow.SalusCloudApi", return_value=api):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDENTIALS)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Salus Cloud (Me@Example.com)"
    assert result["data"] == CREDENTIALS
    assert result["result"].unique_id == "me@example.com"


async def test_it500_account(hass: HomeAssistant, enable_custom: None) -> None:
    result = await _start(hass, "it500")
    with patch("custom_components.salus_cloud.config_flow.SalusIt500Api", return_value=_it500_api()):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDENTIALS)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Salus iT500 (Me@Example.com)"
    assert result["data"] == {**CREDENTIALS, "account_type": "it500"}
    # A Salus Cloud account with the same email address can be added as well
    assert result["result"].unique_id == "it500_me@example.com"


@pytest.mark.parametrize(
    ("api", "error"),
    [
        (_it500_api(error=SalusCloudAuthenticationError("rejected")), "invalid_auth"),
        (_it500_api(devices=[]), "no_devices"),
    ],
)
async def test_it500_errors(hass: HomeAssistant, enable_custom: None, api: AsyncMock, error: str) -> None:
    result = await _start(hass, "it500")
    with patch("custom_components.salus_cloud.config_flow.SalusIt500Api", return_value=api):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDENTIALS)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}


async def test_it500_account_added_twice(hass: HomeAssistant, enable_custom: None) -> None:
    MockConfigEntry(
        domain=DOMAIN, data={**CREDENTIALS, "account_type": "it500"}, unique_id="it500_me@example.com"
    ).add_to_hass(hass)
    result = await _start(hass, "it500")
    result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDENTIALS)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_it500_reauthentication_logs_in_to_the_it500_cloud(hass: HomeAssistant, enable_custom: None) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, data={**CREDENTIALS, "account_type": "it500"}, unique_id="it500_me@example.com"
    )
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"

    api = _it500_api()
    with (
        patch("custom_components.salus_cloud.config_flow.SalusIt500Api", return_value=api) as it500,
        patch("custom_components.salus_cloud.config_flow.SalusCloudApi") as cloud,
    ):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"password": "new"})

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data["password"] == "new"
    assert it500.call_args.args[:2] == ("Me@Example.com", "new")
    assert not cloud.called
