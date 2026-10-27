"""Data coordinator of a Salus iT500 account: polled attributes and commands."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from ..api import SalusCloudAuthenticationError, SalusCloudConnectionError
from ..const import (
    CONFIRM_REFRESH_DELAY_SECONDS,
    DOMAIN,
    METADATA_REFRESH_SECONDS,
    PENDING_TIMEOUT_SECONDS,
    STALE_AFTER_SECONDS,
)
from ..state import DeviceStateStore
from .api import It500Device, SalusIt500Api
from .model import (
    FIRMWARE,
    REFRESH,
    REFRESH_SECONDS,
    It500Thermostat,
    Mode,
    Zone,
    hot_water_mode_writes,
    is_plausible,
    mode_writes,
    setpoint_writes,
    turn_on_writes,
)

_LOGGER = logging.getLogger(__name__)

# Reading the cloud copy of the attributes sends nothing to the thermostat
SCAN_INTERVAL_SECONDS = 60
# Pause before an attribute of the same command is written again (leaving a temporary hold through manual mode), so
# the thermostat takes the mode in between (salus-it500-cloud waits as long)
REWRITE_DELAY_SECONDS = 0.5

type It500ConfigEntry = ConfigEntry[It500Coordinator]


class It500Coordinator(DataUpdateCoordinator[dict[str, It500Thermostat]]):
    """Keeps the iT500 thermostats of an account up to date and sends their commands."""

    config_entry: It500ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: It500ConfigEntry,
        api: SalusIt500Api,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Initialize coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_it500",
            update_interval=timedelta(seconds=SCAN_INTERVAL_SECONDS),
        )
        self.api = api
        self._clock = clock
        self._store = DeviceStateStore(pending_timeout=PENDING_TIMEOUT_SECONDS, max_age=STALE_AFTER_SECONDS)
        self._devices: list[It500Device] | None = None
        self._devices_fetched_at = 0.0
        self._cancel_confirmation: CALLBACK_TYPE | None = None

    def get_device(self, device_id: str) -> It500Thermostat | None:
        """Return current data of a thermostat."""
        return (self.data or {}).get(device_id)

    def device_info(self, device: It500Thermostat) -> DeviceInfo:
        """Return device registry info of a thermostat."""
        info = DeviceInfo(
            identifiers={(DOMAIN, device.unique_id)},
            name=device.name,
            manufacturer="Salus",
            model="iT500",
            serial_number=device.serial or None,
        )
        if firmware := device.attributes.get(FIRMWARE):
            info["sw_version"] = firmware
        return info

    async def _async_update_data(self) -> dict[str, It500Thermostat]:
        now = self._clock()
        try:
            await self._async_refresh_devices(now)
            for device in self._devices or []:
                try:
                    attributes = await self.api.get_attributes(device.id)
                except SalusCloudConnectionError as err:
                    _LOGGER.debug("Could not read iT500 %s: %s", device.id, err)
                    continue
                if not is_plausible(attributes):
                    _LOGGER.debug("Ignoring the 32 °C / 32 °C reading of a broken session, logging in again")
                    self.api.reset_session()
                    continue
                self._store.update_reported(device.id, "", attributes, now)
        except SalusCloudAuthenticationError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        if self._devices and not any(self._store.is_fresh(device.id, now) for device in self._devices):
            raise UpdateFailed("Could not read the iT500 thermostats from Salus")
        return self._build_data(now)

    async def _async_refresh_devices(self, now: float) -> None:
        if self._devices is not None and now - self._devices_fetched_at < METADATA_REFRESH_SECONDS:
            return
        try:
            self._devices = await self.api.get_devices()
        except SalusCloudConnectionError as err:
            if self._devices is None:
                raise UpdateFailed(f"Error communicating with Salus iT500: {err}") from err
            _LOGGER.warning("Failed to refresh the iT500 device list, using the previous one: %s", err)
            return
        self._devices_fetched_at = now

    def _build_data(self, now: float) -> dict[str, It500Thermostat]:
        return {
            device.id: It500Thermostat(
                id=device.id,
                serial=device.serial,
                attributes=self._store.properties(device.id, now),
                fresh=self._store.is_fresh(device.id, now),
            )
            for device in self._devices or []
        }

    async def async_shutdown(self) -> None:
        """Stop polling and a pending confirmation."""
        await super().async_shutdown()
        if self._cancel_confirmation is not None:
            self._cancel_confirmation()
            self._cancel_confirmation = None

    async def async_set_temperature(self, device_id: str, zone: Zone, temperature: float) -> None:
        """Set the target temperature of a zone; in schedule mode the thermostat holds it until the next change."""
        await self._async_write(device_id, setpoint_writes(zone, temperature))

    async def async_set_mode(self, device_id: str, zone: Zone, mode: Mode) -> None:
        """Switch a zone off or to schedule, temporary hold or manual mode."""
        device = self._require_device(device_id)
        await self._async_write(device_id, mode_writes(device.attributes, zone, mode))

    async def async_turn_on(self, device_id: str, zone: Zone) -> None:
        """Turn a zone on again in the mode it had before it was switched off."""
        await self._async_write(device_id, turn_on_writes(zone))

    async def async_set_hot_water_mode(self, device_id: str, mode: str) -> None:
        """Set the hot water mode: auto, once, on or off."""
        await self._async_write(device_id, hot_water_mode_writes(mode))

    async def async_refresh_device(self, device_id: str) -> None:
        """Ask a thermostat to report all its values now."""
        await self._async_write(device_id, [])

    async def _async_write(self, device_id: str, writes: list[tuple[str, str]]) -> None:
        """Wake the thermostat and write the attributes one by one; they are shown until it reports them."""
        device = self._require_device(device_id)
        name = device.name.strip()
        written: dict[str, str] = {}
        try:
            await self.api.set_attribute(device.id, REFRESH, REFRESH_SECONDS)
            for attribute, value in writes:
                if attribute in written:
                    await asyncio.sleep(REWRITE_DELAY_SECONDS)
                await self.api.set_attribute(device.id, attribute, value)
                written[attribute] = value
        except SalusCloudAuthenticationError as err:
            self.config_entry.async_start_reauth(self.hass)
            raise _command_error(name) from err
        except SalusCloudConnectionError as err:
            _LOGGER.warning("iT500 %s did not accept %s: %s", name, writes, err)
            raise _command_error(name) from err
        finally:
            if written:
                now = self._clock()
                self._store.set_pending(device.id, written, now)
                self.async_set_updated_data(self._build_data(now))
        self._schedule_confirmation_refresh()

    def _require_device(self, device_id: str) -> It500Thermostat:
        device = self.get_device(device_id)
        if device is None:
            raise HomeAssistantError(
                f"Salus device {device_id} not found",
                translation_domain=DOMAIN,
                translation_key="device_not_found",
                translation_placeholders={"device_id": device_id},
            )
        return device

    @callback
    def _schedule_confirmation_refresh(self) -> None:
        if self._cancel_confirmation is not None:
            self._cancel_confirmation()
        self._cancel_confirmation = async_call_later(
            self.hass, CONFIRM_REFRESH_DELAY_SECONDS, self._async_confirmation_refresh
        )

    async def _async_confirmation_refresh(self, _now: datetime) -> None:
        self._cancel_confirmation = None
        await self.async_request_refresh()


def _command_error(name: str) -> HomeAssistantError:
    return HomeAssistantError(
        f"Salus device did not accept the command: {name}",
        translation_domain=DOMAIN,
        translation_key="command_not_accepted",
        translation_placeholders={"devices": name},
    )
