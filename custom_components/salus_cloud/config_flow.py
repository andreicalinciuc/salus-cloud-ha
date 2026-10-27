"""Config flow for Salus Cloud integration."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import NumberSelector, NumberSelectorConfig, NumberSelectorMode

from .api import SalusCloudApi, SalusCloudAuthenticationError, SalusCloudConnectionError
from .const import (
    ACCOUNT_TYPE_IT500,
    CONF_ACCOUNT_TYPE,
    CONF_HUMIDITY_INTERVAL,
    CONF_SYNC_MODES,
    DEFAULT_HUMIDITY_INTERVAL_MINUTES,
    DOMAIN,
)
from .it500 import is_it500_entry
from .it500.api import SalusIt500Api

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
    }
)
STEP_REAUTH_DATA_SCHEMA = vol.Schema({vol.Required(CONF_PASSWORD): str})


class SalusCloudConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Salus Cloud."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> SalusOptionsFlow:
        """Return the options flow."""
        return SalusOptionsFlow()

    @classmethod
    @callback
    def async_supports_options_flow(cls, config_entry: ConfigEntry) -> bool:
        """Return whether the entry has options; mode synchronization and humidity reading are Salus Cloud only."""
        return not is_it500_entry(config_entry)

    async def _async_validate(self, email: str, password: str, *, it500: bool = False) -> str | None:
        """Log in and look for gateways (iT500: devices); return error key or None."""
        session = async_get_clientsession(self.hass)
        try:
            if it500:
                api = SalusIt500Api(email, password, session)
                await api.authenticate()
                return None if await api.get_devices() else "no_devices"
            cloud_api = SalusCloudApi(email, password, session=session)
            try:
                await cloud_api.authenticate()
                gateways = await cloud_api.get_gateways()
            finally:
                await cloud_api.close()
        except SalusCloudAuthenticationError:
            return "invalid_auth"
        except SalusCloudConnectionError:
            return "cannot_connect"
        except Exception:
            _LOGGER.exception("Unexpected error while validating Salus Cloud login")
            return "unknown"
        return None if gateways else "no_devices"

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask which app the account belongs to: Salus Smart Home (Salus Cloud) or Salus iT500."""
        return self.async_show_menu(step_id="user", menu_options=["cloud", ACCOUNT_TYPE_IT500])

    async def async_step_cloud(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Log in with the account of the Salus Smart Home app."""
        errors: dict[str, str] = {}
        if user_input is not None:
            email = user_input[CONF_EMAIL]
            await self.async_set_unique_id(email.lower())
            self._abort_if_unique_id_configured()
            if (error := await self._async_validate(email, user_input[CONF_PASSWORD])) is None:
                return self.async_create_entry(
                    title=f"Salus Cloud ({email})",
                    data={CONF_EMAIL: email, CONF_PASSWORD: user_input[CONF_PASSWORD]},
                )
            errors["base"] = error
        return self.async_show_form(step_id="cloud", data_schema=STEP_USER_DATA_SCHEMA, errors=errors)

    async def async_step_it500(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Log in with the account of the Salus iT500 app."""
        errors: dict[str, str] = {}
        if user_input is not None:
            email = user_input[CONF_EMAIL]
            # The same email address can have a Salus Cloud account as well
            await self.async_set_unique_id(f"{ACCOUNT_TYPE_IT500}_{email.lower()}")
            self._abort_if_unique_id_configured()
            if (error := await self._async_validate(email, user_input[CONF_PASSWORD], it500=True)) is None:
                return self.async_create_entry(
                    title=f"Salus iT500 ({email})",
                    data={
                        CONF_EMAIL: email,
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        CONF_ACCOUNT_TYPE: ACCOUNT_TYPE_IT500,
                    },
                )
            errors["base"] = error
        return self.async_show_form(step_id=ACCOUNT_TYPE_IT500, data_schema=STEP_USER_DATA_SCHEMA, errors=errors)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Handle rejected credentials."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the current password."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            error = await self._async_validate(
                entry.data[CONF_EMAIL], user_input[CONF_PASSWORD], it500=is_it500_entry(entry)
            )
            if error is None:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )
            errors["base"] = error
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_REAUTH_DATA_SCHEMA,
            errors=errors,
            description_placeholders={"email": entry.data[CONF_EMAIL]},
        )


class SalusOptionsFlow(OptionsFlowWithReload):
    """Options of Salus Cloud integration."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Manage mode synchronization and how often humidity is read."""
        if user_input is not None:
            return self.async_create_entry(
                data={**user_input, CONF_HUMIDITY_INTERVAL: int(user_input[CONF_HUMIDITY_INTERVAL])}
            )
        options = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SYNC_MODES, default=options.get(CONF_SYNC_MODES, False)): bool,
                    vol.Required(
                        CONF_HUMIDITY_INTERVAL,
                        default=options.get(CONF_HUMIDITY_INTERVAL, DEFAULT_HUMIDITY_INTERVAL_MINUTES),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=0, max=120, step=5, unit_of_measurement="min", mode=NumberSelectorMode.BOX
                        )
                    ),
                }
            ),
        )
