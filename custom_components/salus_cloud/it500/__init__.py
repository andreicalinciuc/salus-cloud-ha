"""Salus iT500 thermostats, read and controlled through the cloud of the Salus iT500 app (Arrayent).

The iT500 has its own account and cloud: none of its devices appear in Salus Cloud. The protocol and the meaning of
the attributes follow ZaBug/salus-it500 and Peterka35/salus-it500-cloud (both MIT licensed) and the attribute
descriptions the API returns itself.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from ..api import SalusCloudAuthenticationError, SalusCloudConnectionError
from ..const import ACCOUNT_TYPE_IT500, CONF_ACCOUNT_TYPE
from .api import SalusIt500Api
from .coordinator import It500ConfigEntry, It500Coordinator

PLATFORMS: list[Platform] = [
    Platform.CLIMATE,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.SELECT,
]


def is_it500_entry(entry: ConfigEntry) -> bool:
    """Return whether the entry is a Salus iT500 account."""
    return entry.data.get(CONF_ACCOUNT_TYPE) == ACCOUNT_TYPE_IT500


async def async_setup_it500_entry(hass: HomeAssistant, entry: It500ConfigEntry) -> bool:
    """Set up the thermostats of a Salus iT500 account."""
    api = SalusIt500Api(entry.data[CONF_EMAIL], entry.data[CONF_PASSWORD], async_get_clientsession(hass))
    try:
        await api.authenticate()
    except SalusCloudAuthenticationError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except SalusCloudConnectionError as err:
        raise ConfigEntryNotReady(str(err)) from err

    coordinator = It500Coordinator(hass, entry, api)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True
