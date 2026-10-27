"""Salus iT500 cloud API: login, device list, device attributes and attribute commands."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re

# ElementTree resolves no external entities, and the expat of Python 3.13+ refuses entity expansion attacks
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any

import aiohttp

from ..api import SalusCloudAuthenticationError, SalusCloudConnectionError

_LOGGER = logging.getLogger(__name__)

API_HOST = "https://sal-emea-p01-api.arrayent.com"
LOGIN_URL = f"{API_HOST}/acc/applications/SalusService/sessions"
ZAMAPI_URL = f"{API_HOST}/zdk/services/zamapi"

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=20)
RETRY_DELAY_SECONDS = 2
AUTH_ERROR_STATUSES = {401, 403}
# Error code of a requestFault for an expired security token
INVALID_TOKEN = 106


@dataclass(frozen=True)
class It500Device:
    """Device of the account's device list (devName is a serial number such as "STA00000000")."""

    id: str
    serial: str
    type_id: str


def password_hash(password: str) -> str:
    """Return the password as the API takes it (MD5 hex digest)."""
    return hashlib.md5(password.encode()).hexdigest()


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child(element: ET.Element, name: str) -> str:
    return next(((child.text or "").strip() for child in element if _local(child.tag) == name), "")


def _parse(text: str) -> ET.Element:
    try:
        return ET.fromstring(text)
    except ET.ParseError as err:
        raise SalusCloudConnectionError(f"Unexpected Salus iT500 response: {text[:200]}") from err


def fault_code(text: str) -> int | None:
    """Return the error code of a requestFault document, None for any other response."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return None
    if _local(root.tag) != "requestFault":
        return None
    code = _child(root, "errorCode")
    return int(code) if code.isdigit() else -1


def parse_device_list(text: str) -> list[It500Device]:
    """Return the devices of a getDeviceList response."""
    return [
        It500Device(id=_child(item, "devId"), serial=_child(item, "devName"), type_id=_child(item, "typeId"))
        for item in _parse(text)
        if _local(item.tag) == "devList" and _child(item, "devId")
    ]


def parse_attributes(text: str) -> dict[str, str]:
    """Return the attribute values of a getDeviceAttributesWithValues response."""
    root = _parse(text)
    attributes = {
        name: _child(item, "value")
        for item in root
        if _local(item.tag) == "attrList" and (name := _child(item, "name"))
    }
    if presence := _child(root, "presenceInfo"):
        attributes.setdefault("online", presence)
    return attributes


class SalusIt500Api:
    """Client of the Salus iT500 cloud for one account."""

    def __init__(self, email: str, password: str, session: aiohttp.ClientSession) -> None:
        """Initialize the client; the HTTP session is shared and never closed by the client."""
        self.email = email
        self._password = password
        self._session = session
        self._user_id: str | None = None
        self._token: str | None = None
        self._lock = asyncio.Lock()

    async def authenticate(self) -> None:
        """Log in and get a security token.

        Salus removes special characters from a password when it is set, without telling the user, so a rejected
        password is tried once more without them.
        """
        stripped = re.sub(r"[^A-Za-z0-9]", "", self._password)
        for password in dict.fromkeys((self._password, stripped)):
            status, body = await self._request(
                "post", LOGIN_URL, json={"username": self.email, "password": password_hash(password)}
            )
            try:
                data: dict[str, Any] = json.loads(body)
            except ValueError:
                data = {}
            if status in AUTH_ERROR_STATUSES or "errorCode" in data:
                continue
            if status != 200 or "securityToken" not in data or "userId" not in data:
                raise SalusCloudConnectionError(f"Unexpected Salus iT500 login response (HTTP {status})")
            if password != self._password:
                _LOGGER.info("Salus iT500 accepted the password without its special characters")
                self._password = password
            self._user_id = str(data["userId"])
            self._token = str(data["securityToken"])
            return
        raise SalusCloudAuthenticationError("Invalid email or password")

    async def get_devices(self) -> list[It500Device]:
        """Return the devices of the account."""
        return parse_device_list(await self._call("post", "getDeviceList", {}))

    async def get_attributes(self, device_id: str) -> dict[str, str]:
        """Return all attributes of a device as last reported to the cloud."""
        return parse_attributes(await self._call("post", "getDeviceAttributesWithValues", {"devId": device_id}))

    async def set_attribute(self, device_id: str, name: str, value: str) -> None:
        """Set one attribute; an iT500 reports multiAttributeCapable=false, so one attribute per call."""
        text = await self._call(
            "get", "setMultiDeviceAttributes2", {"devId": device_id, "name1": name, "value1": value}
        )
        code = _child(_parse(text), "retCode")
        if code != "0":
            raise SalusCloudConnectionError(f"Salus iT500 refused {name}={value} (retCode {code or '?'})")

    def reset_session(self) -> None:
        """Forget the security token; the next request logs in again."""
        self._token = None

    async def _call(self, method: str, path: str, params: dict[str, str]) -> str:
        """Send an API request, logging in again once when the security token was rejected."""
        async with self._lock:
            for attempt in range(2):
                if self._token is None:
                    await self.authenticate()
                values = {**params, "userId": self._user_id or "", "secToken": self._token or ""}
                argument = "data" if method == "post" else "params"
                status, body = await self._request(method, f"{ZAMAPI_URL}/{path}", **{argument: values})
                code = fault_code(body)
                if status in AUTH_ERROR_STATUSES or code == INVALID_TOKEN:
                    _LOGGER.debug("Salus iT500 rejected the security token, logging in again")
                    self._token = None
                    if attempt == 0:
                        continue
                    raise SalusCloudAuthenticationError("Salus iT500 rejected a new security token")
                if status != 200 or code is not None:
                    raise SalusCloudConnectionError(f"Salus iT500 {path} failed (HTTP {status}, error {code})")
                return body
        raise SalusCloudConnectionError(f"Salus iT500 {path} failed")

    async def _request(self, method: str, url: str, **kwargs: Any) -> tuple[int, str]:
        """Send a request; a network or server error is retried once, as the API fails intermittently."""
        problem = ""
        for attempt in range(2):
            if attempt:
                await asyncio.sleep(RETRY_DELAY_SECONDS)
            try:
                async with self._session.request(method, url, timeout=REQUEST_TIMEOUT, **kwargs) as response:
                    body = await response.text()
            except (aiohttp.ClientError, TimeoutError) as err:
                problem = str(err) or type(err).__name__
                continue
            if response.status < 500:
                return response.status, body
            problem = f"HTTP {response.status}"
        raise SalusCloudConnectionError(f"Salus iT500 request failed: {problem}")
