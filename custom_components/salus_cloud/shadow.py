"""Helpers for Salus device shadows: property names, lookups and value conversions.

A shadow property is named "<endpoint>:<cluster>:<name>", e.g. "ep1:sTherS:HeatingSetpoint_x100". The same
cluster and name appear under different endpoints per device family (ep9 for iT600, ep1/ep2 for iT800), so most
lookups match "<cluster>:<name>" only. Commands are sent through the matching "Set<name>" property.
"""

from __future__ import annotations

import re
from typing import Any


def as_int(value: Any) -> int | None:
    """Return the value when it is an integer (booleans are not), otherwise None."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def as_number(value: Any) -> int | float | None:
    """Return the value when it is a number (booleans are not), otherwise None."""
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def cluster_property(key: str) -> str:
    """Return the property without endpoint ("ep1:sTherS:SystemMode" -> "sTherS:SystemMode")."""
    endpoint, _, rest = key.partition(":")
    return rest if endpoint.startswith("ep") and rest else key


def endpoint(key: str) -> str:
    """Return the endpoint of a property ("ep1:sTherS:SystemMode" -> "ep1")."""
    return key.partition(":")[0]


def endpoint_number(key: str) -> int:
    """Return the number of the endpoint of a property ("ep10:sOnOffS:OnOff" -> 10), -1 without one."""
    number = endpoint(key).removeprefix("ep")
    return int(number) if number.isdigit() else -1


def property_name(key: str) -> str:
    """Return the property name without endpoint and cluster ("ep1:sTherS:SystemMode" -> "SystemMode")."""
    return key.rsplit(":", 1)[-1]


def is_command(key: str) -> bool:
    """Return whether the property is a command ("ep1:sTherS:SetSystemMode")."""
    return property_name(key).startswith("Set")


def set_property(key: str) -> str:
    """Return the command property of a reported one ("ep1:sTherS:SystemMode" -> "ep1:sTherS:SetSystemMode")."""
    prefix, _, name = key.rpartition(":")
    return f"{prefix}:Set{name}"


def reported_property(key: str) -> str:
    """Return the reported property of a command ("ep1:sTherS:SetSystemMode" -> "ep1:sTherS:SystemMode")."""
    prefix, separator, name = key.partition(":Set")
    return f"{prefix}:{name}" if separator else key


def find_properties(properties: dict[str, Any], pattern: re.Pattern[str], *, with_endpoint: bool = False) -> list[str]:
    """Return the reported properties (sorted, commands excluded) matching the pattern.

    The pattern is matched against "<cluster>:<name>", or the full name when with_endpoint is set.
    """
    return [
        key
        for key in sorted(properties)
        if not is_command(key) and pattern.search(key if with_endpoint else cluster_property(key))
    ]


def find_property(properties: dict[str, Any], pattern: re.Pattern[str], *, with_endpoint: bool = False) -> str | None:
    """Return the first reported property (sorted, commands excluded) matching the pattern."""
    found = find_properties(properties, pattern, with_endpoint=with_endpoint)
    return found[0] if found else None


def scaled_value(key: str, value: Any) -> float | None:
    """Return a numeric value scaled by the _x100 / _x10 suffix of its property name."""
    if (number := as_number(value)) is None:
        return None
    name = property_name(key)
    if name.endswith("_x100"):
        return round(number / 100, 2)
    if name.endswith("_x10"):
        return round(number / 10, 2)
    return float(number)


def signed_byte(value: Any) -> Any:
    """Return a value reported as an unsigned byte as the signed value it stands for (251 -> -5).

    Temperature calibration is reported this way but written signed.
    """
    if (number := as_int(value)) is not None and 127 < number < 256:
        return number - 256
    return value


def version_string(value: Any) -> str | None:
    """Return a reported firmware or hardware version as text, None when missing."""
    if as_int(value) is not None or (isinstance(value, str) and value):
        return str(value)
    return None
