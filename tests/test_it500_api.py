"""Salus iT500 cloud client and the decoding of what an iT500 reports."""

import hashlib
from typing import Any
from unittest.mock import patch

import pytest

from custom_components.salus_cloud.api import SalusCloudAuthenticationError, SalusCloudConnectionError
from custom_components.salus_cloud.it500.api import LOGIN_URL, ZAMAPI_URL, SalusIt500Api, parse_attributes
from custom_components.salus_cloud.it500.model import (
    ZONE_1,
    ZONE_2,
    It500Thermostat,
    Mode,
    hot_water_mode_writes,
    is_plausible,
    mode_writes,
    setpoint_writes,
)

from . import it500_fixtures as fx


class _Response:
    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self._body = body

    async def text(self) -> str:
        return self._body

    async def __aenter__(self) -> "_Response":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None


class FakeSession:
    """aiohttp session answering requests in order and recording them."""

    def __init__(self, *responses: tuple[int, str] | Exception) -> None:
        self.responses = list(responses)
        self.requests: list[tuple[str, str, dict[str, Any]]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> _Response:
        self.requests.append((method, url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return _Response(*response)


def _api(*responses: tuple[int, str] | Exception, password: str = "secret") -> tuple[SalusIt500Api, FakeSession]:
    session = FakeSession(*responses)
    return SalusIt500Api("me@example.com", password, session), session  # type: ignore[arg-type]


async def test_login_sends_the_md5_of_the_password_and_requests_carry_the_token() -> None:
    api, session = _api((200, fx.login_json()), (200, fx.device_list_xml(fx.DEVICE_ID)))

    devices = await api.get_devices()

    assert [(device.id, device.serial) for device in devices] == [(fx.DEVICE_ID, fx.SERIAL)]
    method, url, kwargs = session.requests[0]
    assert (method, url) == ("post", LOGIN_URL)
    assert kwargs["json"] == {"username": "me@example.com", "password": hashlib.md5(b"secret").hexdigest()}
    method, url, kwargs = session.requests[1]
    assert (method, url) == ("post", f"{ZAMAPI_URL}/getDeviceList")
    assert kwargs["data"] == {"userId": fx.USER_ID, "secToken": "token1"}


async def test_rejected_password_is_tried_without_special_characters() -> None:
    """Salus drops special characters from a password when it is set."""
    api, session = _api((403, fx.LOGIN_REJECTED), (200, fx.login_json()), password="se-cret!")

    await api.authenticate()

    assert [kwargs["json"]["password"] for _, _, kwargs in session.requests] == [
        hashlib.md5(b"se-cret!").hexdigest(),
        hashlib.md5(b"secret").hexdigest(),
    ]


async def test_rejected_login() -> None:
    api, session = _api((403, fx.LOGIN_REJECTED))
    with pytest.raises(SalusCloudAuthenticationError):
        await api.authenticate()
    assert len(session.requests) == 1


async def test_expired_token_logs_in_again() -> None:
    api, session = _api(
        (200, fx.login_json("token1")),
        (200, fx.fault_xml(106)),
        (200, fx.login_json("token2")),
        (200, fx.attributes_xml(fx.SINGLE_ZONE)),
    )

    attributes = await api.get_attributes(fx.DEVICE_ID)

    assert attributes["A84"] == "1750"
    assert session.requests[-1][2]["data"] == {"devId": fx.DEVICE_ID, "userId": fx.USER_ID, "secToken": "token2"}


async def test_other_api_errors_are_connection_errors() -> None:
    api, _ = _api((200, fx.login_json()), (200, fx.fault_xml(109, "Device does not exist.")))
    with pytest.raises(SalusCloudConnectionError):
        await api.get_attributes(fx.DEVICE_ID)


async def test_server_errors_are_retried_once() -> None:
    api, session = _api((503, ""), (200, fx.login_json()), (200, fx.device_list_xml()))
    with patch("custom_components.salus_cloud.it500.api.RETRY_DELAY_SECONDS", 0):
        assert await api.get_devices() == []
    assert len(session.requests) == 3

    api, _ = _api(TimeoutError(), TimeoutError())
    with (
        patch("custom_components.salus_cloud.it500.api.RETRY_DELAY_SECONDS", 0),
        pytest.raises(SalusCloudConnectionError),
    ):
        await api.authenticate()


async def test_set_attribute_sends_one_attribute_and_checks_the_result() -> None:
    api, session = _api((200, fx.login_json()), (200, fx.set_xml()), (200, fx.set_xml(3)))

    await api.set_attribute(fx.DEVICE_ID, "A85", "2100")
    with pytest.raises(SalusCloudConnectionError):
        await api.set_attribute(fx.DEVICE_ID, "A89", "1")

    method, url, kwargs = session.requests[1]
    assert (method, url) == ("get", f"{ZAMAPI_URL}/setMultiDeviceAttributes2")
    assert kwargs["params"] == {
        "devId": fx.DEVICE_ID,
        "name1": "A85",
        "value1": "2100",
        "userId": fx.USER_ID,
        "secToken": "token1",
    }


def _thermostat(**changes: str) -> It500Thermostat:
    return It500Thermostat(id=fx.DEVICE_ID, serial=fx.SERIAL, attributes={**fx.SINGLE_ZONE, **changes}, fresh=True)


def test_decoding_of_a_real_single_zone_thermostat() -> None:
    thermostat = _thermostat()

    assert thermostat.name == "Home"
    assert thermostat.is_thermostat
    assert thermostat.zones == [ZONE_1]
    assert not thermostat.has_hot_water
    assert thermostat.room_temperature(ZONE_1) == 17.5
    assert thermostat.setpoint(ZONE_1) == 12.1
    assert thermostat.mode(ZONE_1) is Mode.OFF  # off wins over manual
    assert thermostat.heating(ZONE_1) is False
    assert thermostat.battery_low is False
    assert thermostat.online is True
    assert thermostat.rssi == -56


def test_modes_zones_and_hot_water() -> None:
    assert _thermostat(A89="0").mode(ZONE_1) is Mode.MANUAL
    assert _thermostat(A89="0", A92="0", A88="1").mode(ZONE_1) is Mode.TEMPORARY_HOLD
    assert _thermostat(A89="0", A92="0").mode(ZONE_1) is Mode.SCHEDULE
    assert _thermostat(S06="1").zones == [ZONE_1, ZONE_2]
    hot_water = _thermostat(S06="2", C42="2", C45="1")
    assert hot_water.has_hot_water
    assert hot_water.hot_water_mode == "on"
    assert hot_water.hot_water_on is True
    assert _thermostat(S03="1").battery_low is True
    assert _thermostat(desc="").name == fx.SERIAL


def test_presence_info_is_used_without_online_attribute() -> None:
    attributes = dict(fx.SINGLE_ZONE)
    del attributes["online"]
    assert parse_attributes(fx.attributes_xml(attributes, presence="0"))["online"] == "0"


def test_broken_session_reading_is_not_plausible() -> None:
    assert is_plausible(fx.SINGLE_ZONE)
    assert not is_plausible({**fx.SINGLE_ZONE, "A84": "3200", "A85": "3200"})


def test_command_writes() -> None:
    attributes = {**fx.SINGLE_ZONE, "A89": "0", "A92": "0", "A88": "0"}
    assert setpoint_writes(ZONE_2, 20.04) == [("B85", "2000")]
    assert setpoint_writes(ZONE_1, 21.5) == [("A85", "2150")]
    assert mode_writes(attributes, ZONE_1, Mode.OFF) == [("A89", "1")]
    assert mode_writes(attributes, ZONE_1, Mode.MANUAL) == [("A92", "1")]
    assert mode_writes(attributes, ZONE_1, Mode.TEMPORARY_HOLD) == [("A88", "1")]
    assert mode_writes(attributes, ZONE_1, Mode.SCHEDULE) == []
    # Leaving off clears the off flag last
    assert mode_writes(fx.SINGLE_ZONE, ZONE_1, Mode.SCHEDULE) == [("A92", "0"), ("A89", "0")]
    # A temporary hold ends through manual mode
    assert mode_writes({**attributes, "A88": "1"}, ZONE_1, Mode.SCHEDULE) == [
        ("A92", "1"),
        ("A88", "0"),
        ("A92", "0"),
    ]
    assert hot_water_mode_writes("off") == [("C42", "3")]
