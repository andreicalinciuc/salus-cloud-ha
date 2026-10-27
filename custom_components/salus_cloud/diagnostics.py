"""Diagnostics for Salus Cloud: device list with the raw shadow properties each device reports."""

from __future__ import annotations

import re
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant

from .coordinator import SalusConfigEntry

# Identifiers and personal data; device models, names and shadow property names stay visible
TO_REDACT = {
    CONF_EMAIL,
    CONF_PASSWORD,
    "id",
    "device_code",
    "_gateway_id",
    "occupants_permissions",
    "email",
    "invitation_email",
    "first_name",
    "last_name",
    "phone_number",
}


# Network details, hardware addresses, cloud identities and debug logs a gateway may report (Wi-Fi name and
# password, IP addresses, MAC / EUI, AWS certificate, device list)
NETWORK_PROPERTY = re.compile(
    r"SSID|Password|Passwd|IPAddr|IpAddr|IPv|WiFiIP|Subnet|Netmask|Router|DNS|MAC|EUI|PANID|PanID|ARN|CloudID|Cert"
    r"|DebugMsg|NetMsg|FullList",
    re.I,
)


def _redact_properties(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        key: "**REDACTED**" if NETWORK_PROPERTY.search(key.rsplit(":", 1)[-1]) else value
        for key, value in properties.items()
    }


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: SalusConfigEntry) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    devices = [
        {
            "name": device.info.get("name"),
            "model": device.info.get("model"),
            "category": (device.info.get("category") or {}).get("name"),
            "property_family": device.names.family,
            "fresh": device.fresh,
            "shadow_device_index": device.shadow_index,
            "shadow_properties": _redact_properties(device.properties),
        }
        for device in (coordinator.data or {}).values()
    ]
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "options": dict(entry.options),
        "push_available": coordinator.push_available,
        "gateways": [
            {
                "name": gateway.name,
                "model": gateway.model,
                "fresh": coordinator.gateway_fresh(gateway.id),
                "shadow_properties": _redact_properties(coordinator.gateway_properties(gateway.id)),
            }
            for gateway in coordinator.gateways
        ],
        "devices": devices,
    }
