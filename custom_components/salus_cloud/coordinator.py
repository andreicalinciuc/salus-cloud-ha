"""Data coordinator for Salus Cloud: device states, commands and thermostat mode synchronization."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    GatewayInfo,
    SalusCloudApi,
    SalusCloudAuthenticationError,
    SalusCloudConnectionError,
    SalusMetadata,
)
from .const import (
    CONF_HUMIDITY_INTERVAL,
    CONF_SYNC_MODES,
    CONFIRM_REFRESH_DELAY_SECONDS,
    DEFAULT_HUMIDITY_INTERVAL_MINUTES,
    DEFAULT_SHADOW_INDEX,
    DOMAIN,
    GATEWAY_SHADOW_INDEX,
    HOLD_TYPE_MANUAL,
    HOLD_TYPE_SCHEDULE,
    HOLD_TYPE_STANDBY,
    METADATA_REFRESH_SECONDS,
    PENDING_TIMEOUT_SECONDS,
    PUSH_SCAN_INTERVAL_SECONDS,
    SCAN_INTERVAL_SECONDS,
    STALE_AFTER_SECONDS,
)
from .device import SalusDevice
from .gateway import FIRMWARE_PATTERN as GATEWAY_FIRMWARE_PATTERN
from .gateway import HARDWARE_PATTERN as GATEWAY_HARDWARE_PATTERN
from .mqtt import SalusMqttConnection
from .properties import detect_property_names
from .shadow import endpoint, find_property, set_property, version_string
from .state import DeviceStateStore, extract_reported

_LOGGER = logging.getLogger(__name__)

FIRMWARE_PATTERN = re.compile(r"^sZDO:FirmwareVersion$")
HARDWARE_PATTERN = re.compile(r"^sBasicS:HardwareVersion$")

# DeviceInfo gained via_device_id (and deprecated via_device) in a 2026 Home Assistant release
VIA_DEVICE_ID_SUPPORTED = "via_device_id" in DeviceInfo.__annotations__


type SalusConfigEntry = ConfigEntry[SalusCloudCoordinator]


class SalusCloudCoordinator(DataUpdateCoordinator[dict[str, SalusDevice]]):
    """Keeps Salus device data up to date and sends commands to devices."""

    config_entry: SalusConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: SalusConfigEntry,
        api: SalusCloudApi,
        *,
        connection_factory: Callable[..., SalusMqttConnection] = SalusMqttConnection,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Initialize coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=SCAN_INTERVAL_SECONDS),
        )
        self.api = api
        self._connection_factory = connection_factory
        self._clock = clock
        self._store = DeviceStateStore(pending_timeout=PENDING_TIMEOUT_SECONDS, max_age=STALE_AFTER_SECONDS)
        self._metadata: SalusMetadata | None = None
        self._metadata_fetched_at = 0.0
        self._connection: SalusMqttConnection | None = None
        self._cancel_confirmation: CALLBACK_TYPE | None = None
        self._cancel_humidity_reads: CALLBACK_TYPE | None = None
        self._humidity_reads_failing = False
        self.push_available = False
        # Gateway id -> device registry id of the gateway device
        self.gateway_device_ids: dict[str, str] = {}

    @property
    def sync_modes(self) -> bool:
        """Return whether a mode change is applied to all thermostats of the gateway."""
        return bool(self.config_entry.options.get(CONF_SYNC_MODES, False))

    @property
    def humidity_interval(self) -> int:
        """Return the minutes between humidity readings requested from devices, 0 when turned off."""
        return int(self.config_entry.options.get(CONF_HUMIDITY_INTERVAL, DEFAULT_HUMIDITY_INTERVAL_MINUTES))

    @property
    def gateways(self) -> list[GatewayInfo]:
        """Return gateways of the account."""
        return self._metadata.gateways if self._metadata else []

    @property
    def rules(self) -> list[dict[str, Any]]:
        """Return OneTouch rules of all gateways."""
        return self._metadata.rules if self._metadata else []

    def get_gateway(self, gateway_id: str) -> GatewayInfo | None:
        """Return gateway by id."""
        return next((gateway for gateway in self.gateways if gateway.id == gateway_id), None)

    def get_device(self, device_id: str) -> SalusDevice | None:
        """Return current data of a device."""
        return (self.data or {}).get(device_id)

    def device_info(self, device: SalusDevice) -> DeviceInfo:
        """Return device registry info of a device linked to its gateway."""
        info = DeviceInfo(
            identifiers={(DOMAIN, device.id)},
            name=device.name,
            manufacturer="Salus",
            model=device.model or "iT600",
        )
        if (firmware := _version(device.properties, FIRMWARE_PATTERN)) is not None:
            info["sw_version"] = firmware
        if (hardware := _version(device.properties, HARDWARE_PATTERN)) is not None:
            info["hw_version"] = hardware
        self.link_to_gateway(info, device.gateway_id)
        return info

    def gateway_versions(self, gateway_id: str) -> tuple[str | None, str | None]:
        """Return software and hardware version a gateway reports."""
        properties = self.gateway_properties(gateway_id)
        return (
            _version(properties, GATEWAY_FIRMWARE_PATTERN, with_endpoint=True),
            _version(properties, GATEWAY_HARDWARE_PATTERN, with_endpoint=True),
        )

    def link_to_gateway(self, info: DeviceInfo, gateway_id: str) -> None:
        """Show a device as connected via its gateway.

        Newer Home Assistant versions take the registry id (via_device_id) and deprecate the identifier
        (via_device); older ones only accept the identifier.
        """
        if (gateway_device_id := self.gateway_device_ids.get(gateway_id)) is None:
            return
        if VIA_DEVICE_ID_SUPPORTED:
            info["via_device_id"] = gateway_device_id  # type: ignore[typeddict-unknown-key]
        else:
            info["via_device"] = (DOMAIN, gateway_id)

    def _device_codes(self) -> list[str]:
        devices = self._metadata.devices if self._metadata else []
        return [device["device_code"] for device in devices if device.get("device_code")]

    def gateway_properties(self, gateway_id: str) -> dict[str, Any]:
        """Return the shadow properties a gateway (e.g. a Wi-Fi receiver) reports."""
        gateway = self.get_gateway(gateway_id)
        return self._store.properties(gateway.device_code, self._clock()) if gateway and gateway.device_code else {}

    def gateway_fresh(self, gateway_id: str) -> bool:
        """Return whether recent shadow data of a gateway is known."""
        gateway = self.get_gateway(gateway_id)
        return bool(gateway and gateway.device_code and self._store.is_fresh(gateway.device_code, self._clock()))

    def _gateway_codes(self) -> set[str]:
        return {gateway.device_code for gateway in self.gateways if gateway.device_code}

    def _store_reported(self, device_code: str, shadow: dict[str, Any], now: float) -> None:
        if (reported := extract_reported(shadow, all_indexes=device_code in self._gateway_codes())) is not None:
            self._store.update_reported(device_code, reported[0], reported[1], now)

    async def _async_update_gateways(self, now: float) -> None:
        # Gateways the device list does not include are polled separately and never subscribed to: a gateway
        # shadow the account may not read must neither fail the device update nor turn off pushed updates.
        codes = sorted(self._gateway_codes() - set(self._device_codes()))
        if not codes:
            return
        try:
            shadows = await self.api.get_device_shadows(codes)
        except SalusCloudConnectionError as err:
            _LOGGER.debug("Could not read gateway states: %s", err)
            return
        for device_code, shadow in shadows.items():
            self._store_reported(device_code, shadow, now)

    async def _async_update_data(self) -> dict[str, SalusDevice]:
        now = self._clock()
        try:
            if self._metadata is None or now - self._metadata_fetched_at >= METADATA_REFRESH_SECONDS:
                await self._async_refresh_metadata(now)
            try:
                shadows = await self.api.get_device_shadows(self._device_codes())
            except SalusCloudConnectionError as err:
                if not any(self._store.is_fresh(code, now) for code in self._device_codes()):
                    raise UpdateFailed(f"Error communicating with Salus Cloud: {err}") from err
                _LOGGER.warning("Failed to refresh device states, keeping last known states: %s", err)
                shadows = {}
        except SalusCloudAuthenticationError as err:
            raise ConfigEntryAuthFailed(str(err)) from err

        for device_code, shadow in shadows.items():
            self._store_reported(device_code, shadow, now)
        try:
            await self._async_update_gateways(now)
        except SalusCloudAuthenticationError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        return self._build_data(now)

    async def _async_refresh_metadata(self, now: float) -> None:
        try:
            metadata = await self.api.fetch_metadata()
        except SalusCloudConnectionError as err:
            if self._metadata is None:
                raise UpdateFailed(f"Error communicating with Salus Cloud: {err}") from err
            _LOGGER.warning("Failed to refresh device list, using the previous one: %s", err)
            return
        self._metadata = metadata
        self._metadata_fetched_at = now
        if self._connection is not None:
            self._connection.set_device_codes(self._device_codes())

    def _build_data(self, now: float) -> dict[str, SalusDevice]:
        data: dict[str, SalusDevice] = {}
        for device in self._metadata.devices if self._metadata else []:
            device_id = device.get("id")
            device_code = device.get("device_code")
            if not device_id or not device_code:
                continue
            properties = self._store.properties(device_code, now)
            data[device_id] = SalusDevice(
                id=device_id,
                code=device_code,
                gateway_id=device.get("_gateway_id", ""),
                info=device,
                properties=properties,
                names=detect_property_names(properties),
                shadow_index=self._store.index(device_code),
                fresh=self._store.is_fresh(device_code, now),
            )
        return data

    async def async_start_connection(self) -> None:
        """Connect to AWS IoT for commands and pushed device state changes."""
        if not self.gateways:
            return
        self._connection = self._connection_factory(
            credentials_provider=self.api.get_iot_credentials,
            client_id_prefix=self.gateways[0].device_code,
            on_shadow_document=self._handle_shadow_document,
            on_push_available=self._handle_push_available,
        )
        await self._connection.async_start(self._device_codes())
        if (minutes := self.humidity_interval) > 0:
            self._cancel_humidity_reads = async_track_time_interval(
                self.hass, self._async_humidity_tick, timedelta(minutes=minutes)
            )

    async def async_shutdown(self) -> None:
        """Stop polling and the AWS IoT connection."""
        await super().async_shutdown()
        if self._cancel_confirmation is not None:
            self._cancel_confirmation()
            self._cancel_confirmation = None
        if self._cancel_humidity_reads is not None:
            self._cancel_humidity_reads()
            self._cancel_humidity_reads = None
        if self._connection is not None:
            await self._connection.async_stop()

    @callback
    def _handle_shadow_document(self, device_code: str, document: dict[str, Any]) -> None:
        if self._metadata is None:
            return
        now = self._clock()
        self._store_reported(device_code, document, now)
        self.async_set_updated_data(self._build_data(now))

    @callback
    def _handle_push_available(self, available: bool) -> None:
        self.push_available = available
        self.update_interval = timedelta(seconds=PUSH_SCAN_INTERVAL_SECONDS if available else SCAN_INTERVAL_SECONDS)

    def _thermostat_targets(self, device: SalusDevice) -> list[SalusDevice]:
        """Return the thermostats a mode change applies to (all of the gateway when synchronized)."""
        if not self.sync_modes:
            return [device]
        return [other for other in self.data.values() if other.gateway_id == device.gateway_id and other.is_thermostat]

    async def async_set_hold_type(self, device_id: str, hold_type: int) -> None:
        """Set hold type of a thermostat, or of all thermostats of its gateway when modes are synchronized."""
        device = self._require_device(device_id)
        await self._async_send(
            self._thermostat_targets(device),
            lambda target: {target.names.set_hold_type: hold_type},
        )

    async def async_set_hvac_mode(self, device_id: str, turn_on: bool) -> None:
        """Set heating on or off, or all thermostats of the gateway when modes are synchronized.

        Most thermostats use the hold type for this. The iT800 family ignores hold type changes for
        the HVAC mode and additionally needs its SystemMode property. The matching hold type is sent
        as well so the reported preset stays consistent with the mode.
        """
        device = self._require_device(device_id)

        def command(target: SalusDevice) -> dict[str, Any]:
            names = target.names
            if names.hvac_mode_uses_system_mode:
                return {
                    names.set_system_mode: 4 if turn_on else 0,
                    names.set_hold_type: HOLD_TYPE_SCHEDULE if turn_on else HOLD_TYPE_STANDBY,
                }
            properties: dict[str, Any] = {names.set_hold_type: HOLD_TYPE_SCHEDULE if turn_on else HOLD_TYPE_STANDBY}
            # A device switched off through its system mode (e.g. on the device) stays off with the hold type alone
            if turn_on and target.properties.get(names.system_mode) == 0:
                properties[names.set_system_mode] = 4
            return properties

        await self._async_send(self._thermostat_targets(device), command)

    async def async_set_temperature(self, device_id: str, temperature: float) -> None:
        """Set target temperature of a thermostat (switches it to manual hold)."""
        device = self._require_device(device_id)

        def command(target: SalusDevice) -> dict[str, Any]:
            names = target.names
            properties: dict[str, Any] = {
                names.set_heating_setpoint: round(temperature * 100),
                names.set_hold_type: HOLD_TYPE_MANUAL,
            }
            if names.setpoint_sets_heat_mode:
                properties[names.set_system_mode] = 4
            return properties

        await self._async_send([device], command)

    async def async_set_property(self, device_id: str, reported_key: str, value: int) -> None:
        """Send the Set* command of a reported property (e.g. a calibration) to one device."""
        await self._async_send([self._require_device(device_id)], {set_property(reported_key): value})

    async def async_set_switch(self, device_id: str, turn_on: bool, on_off_key: str | None = None) -> None:
        """Turn a relay or smart plug output on or off (the one of its family unless an OnOff property is given)."""
        device = self._require_device(device_id)
        value = 1 if turn_on else 0
        if on_off_key is not None:
            await self._async_send([device], {set_property(on_off_key): value})
        else:
            await self._async_send([device], lambda target: {target.names.set_on_off: value})

    async def async_set_cover_position(self, device_id: str, level_key: str, position: int) -> None:
        """Move a roller shutter to a position (0 closed, 100 open) with the command the Salus app sends."""
        await self._async_send(
            [self._require_device(device_id)],
            {f"{endpoint(level_key)}:sLevelS:SetMoveToLevel": f"{position:02x}FFFF"},
        )

    async def async_trigger_rule(self, gateway_id: str, rule_trigger_key: str) -> None:
        """Trigger a OneTouch rule of a gateway."""
        gateway = self.get_gateway(gateway_id)
        if gateway is None:
            raise _error("gateway_not_found", f"Salus gateway {gateway_id} not found", gateway_id=gateway_id)
        try:
            await self._async_publish(
                gateway.device_code, GATEWAY_SHADOW_INDEX, {"ep0:sRule:SetTriggerRule": rule_trigger_key}
            )
        except SalusCloudConnectionError as err:
            raise _error("rule_trigger_failed", f"Failed to trigger OneTouch rule: {err}", error=str(err)) from err

    async def async_refresh_device(self, device_id: str) -> None:
        """Ask a device to report all its properties again (an IT800TX takes about 40 seconds)."""
        device = self._require_device(device_id)
        name = device.name.strip()
        if (command := device.refresh_command) is None:
            raise _error("command_not_accepted", f"Salus device does not accept a refresh: {name}", devices=name)
        try:
            await self._async_publish(device.code, device.shadow_index or DEFAULT_SHADOW_INDEX, {command: 1})
        except SalusCloudConnectionError as err:
            raise _error(
                "command_not_accepted", f"Salus device did not accept the command: {name}", devices=name
            ) from err
        if not self.push_available:
            self._schedule_confirmation_refresh()

    async def _async_humidity_tick(self, _now: datetime) -> None:
        await self.async_read_humidity()

    async def async_read_humidity(self) -> None:
        """Ask thermostats with a humidity sensor for a fresh reading; it arrives like any value they report.

        Reads are not settings: nothing is shown as pending, and a failure is only logged (once until reads work
        again, so an offline gateway does not fill the log).
        """
        # Thermostats only: a battery humidity sensor would be woken up every few minutes
        targets = [
            (device, command)
            for device in (self.data or {}).values()
            if device.is_thermostat and (command := device.humidity_read_command)
        ]
        results = await asyncio.gather(
            *(
                self._async_publish(device.code, device.shadow_index or DEFAULT_SHADOW_INDEX, {command: 1})
                for device, command in targets
            ),
            return_exceptions=True,
        )
        failures = [
            (device.name.strip(), result)
            for (device, _), result in zip(targets, results, strict=True)
            if isinstance(result, BaseException)
        ]
        if failures and not self._humidity_reads_failing:
            _LOGGER.warning(
                "Could not ask %s for a humidity reading, will keep trying: %s",
                ", ".join(name for name, _ in failures),
                failures[0][1],
            )
        elif not failures and self._humidity_reads_failing:
            _LOGGER.info("Humidity readings are requested again")
        self._humidity_reads_failing = bool(failures)

    def _require_device(self, device_id: str) -> SalusDevice:
        device = self.get_device(device_id)
        if device is None:
            raise _error("device_not_found", f"Salus device {device_id} not found", device_id=device_id)
        return device

    async def _async_publish(self, device_code: str, device_index: str, properties: dict[str, Any]) -> None:
        if self._connection is None:
            raise SalusCloudConnectionError("Not connected to AWS IoT")
        await self._connection.async_publish_shadow(device_code, device_index, properties)

    async def _async_send(
        self,
        devices: list[SalusDevice],
        properties: dict[str, Any] | Callable[[SalusDevice], dict[str, Any]],
    ) -> None:
        prepared = [(device, properties(device) if callable(properties) else properties) for device in devices]
        results = await asyncio.gather(
            *(
                self._async_publish(device.code, device.shadow_index or DEFAULT_SHADOW_INDEX, device_properties)
                for device, device_properties in prepared
            ),
            return_exceptions=True,
        )
        now = self._clock()
        failed: list[str] = []
        for (device, device_properties), result in zip(prepared, results, strict=True):
            if isinstance(result, BaseException):
                _LOGGER.warning("Device %s did not accept %s: %s", device.name, device_properties, result)
                failed.append(device.name.strip())
            else:
                self._store.set_pending(device.code, device_properties, now)
        if len(failed) < len(devices):
            self.async_set_updated_data(self._build_data(now))
            if not self.push_available:
                self._schedule_confirmation_refresh()
        if failed:
            devices = ", ".join(failed)
            raise _error("command_not_accepted", f"Salus device did not accept the command: {devices}", devices=devices)

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


def _error(key: str, message: str, **placeholders: str) -> HomeAssistantError:
    """Return an error shown translated in the UI; the English message is kept for logs."""
    return HomeAssistantError(
        message, translation_domain=DOMAIN, translation_key=key, translation_placeholders=placeholders
    )


def _version(properties: dict[str, Any], pattern: re.Pattern[str], *, with_endpoint: bool = False) -> str | None:
    return version_string(properties.get(find_property(properties, pattern, with_endpoint=with_endpoint) or ""))
