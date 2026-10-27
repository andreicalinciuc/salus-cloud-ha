"""Base entities of Salus devices and gateways."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SalusCloudCoordinator
from .device import SalusDevice
from .properties import DEFAULT_PROPERTY_NAMES, PropertyNames


class SalusEntity(CoordinatorEntity[SalusCloudCoordinator]):
    """Entity of a Salus device backed by coordinator data.

    With a key the entity gets a short translated name under its device ("Humidity") and the key appended to its
    unique id. Without one it is the main feature of its device (thermostat, relay, contact) and shown with the
    device name only.
    """

    _attr_has_entity_name = True

    def __init__(self, coordinator: SalusCloudCoordinator, device: SalusDevice, key: str | None = None) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._device_id = device.id
        self._attr_device_info = coordinator.device_info(device)
        self._attr_unique_id = f"{DOMAIN}_{device.gateway_id}_{device.id}"
        if key is None:
            self._attr_name = None
        else:
            self._attr_translation_key = key
            self._attr_unique_id += f"_{key}"

    @property
    def device(self) -> SalusDevice | None:
        """Return current data of the device."""
        return self.coordinator.get_device(self._device_id)

    @property
    def shadow_properties(self) -> dict[str, Any]:
        """Return current shadow properties of the device."""
        return self.device.properties if self.device else {}

    @property
    def property_names(self) -> PropertyNames:
        """Return shadow property names used by this device family."""
        device = self.device
        return device.names if device else DEFAULT_PROPERTY_NAMES

    @property
    def available(self) -> bool:
        """Return whether recent state data of the device is known."""
        device = self.device
        return super().available and device is not None and device.fresh


class SalusPropertyEntity(SalusEntity):
    """Entity showing one shadow property of a device, found when the device was set up."""

    def __init__(self, coordinator: SalusCloudCoordinator, device: SalusDevice, key: str, property_key: str) -> None:
        """Initialize the entity for the property."""
        super().__init__(coordinator, device, key)
        self._property_key = property_key

    @property
    def raw_value(self) -> Any:
        """Return the reported value of the property."""
        return self.shadow_properties.get(self._property_key)


class SalusGatewayEntity(CoordinatorEntity[SalusCloudCoordinator]):
    """Entity showing one property a gateway reports, found when the integration was set up."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: SalusCloudCoordinator, gateway_id: str, key: str, property_key: str) -> None:
        """Initialize the entity for the property."""
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
