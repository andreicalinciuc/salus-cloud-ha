"""Base entity for Salus Cloud devices."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SalusCloudCoordinator, SalusDevice
from .properties import PropertyNames, property_names_of


class SalusEntity(CoordinatorEntity[SalusCloudCoordinator]):
    """Entity of a Salus device backed by coordinator data."""

    _attr_has_entity_name = False  # Name includes gateway name to keep entity ids of multiple apartments apart

    def __init__(self, coordinator: SalusCloudCoordinator, device_id: str, device: SalusDevice) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._device_id = device_id
        gateway_id = device.get("_gateway_id", "")
        gateway = coordinator.get_gateway(gateway_id)
        self._attr_name = f"{gateway.name if gateway else 'Salus'} {device.get('name') or device_id}"
        self._attr_unique_id = f"{DOMAIN}_{gateway_id}_{device_id}"
        self._attr_device_info = coordinator.device_info(device)

    @property
    def device_data(self) -> SalusDevice:
        """Return current data of the device."""
        return self.coordinator.get_device(self._device_id) or {}

    @property
    def shadow_properties(self) -> dict[str, Any]:
        """Return current shadow properties of the device."""
        return self.device_data.get("_shadow_properties", {})

    @property
    def property_names(self) -> PropertyNames:
        """Return shadow property names used by this device family."""
        return property_names_of(self.device_data)

    @property
    def available(self) -> bool:
        """Return whether recent state data of the device is known."""
        return super().available and bool(self.device_data.get("_fresh"))


class SalusGatewayEntity(CoordinatorEntity[SalusCloudCoordinator]):
    """Entity of a value a gateway (e.g. the Wi-Fi receiver switching the boiler) reports."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: SalusCloudCoordinator, gateway_id: str, key: str, property_key: str) -> None:
        """Initialize the entity for the gateway property found when the integration was set up."""
        super().__init__(coordinator)
        self._gateway_id = gateway_id
        self._property_key = property_key
        self._attr_translation_key = key
        self._attr_unique_id = f"{DOMAIN}_{gateway_id}_{key}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, gateway_id)})

    @property
    def raw_value(self) -> Any:
        """Return the reported value of the property."""
        return self.coordinator.gateway_properties(self._gateway_id).get(self._property_key)

    @property
    def available(self) -> bool:
        """Return whether recent state data of the gateway is known."""
        return super().available and self.coordinator.gateway_fresh(self._gateway_id)
