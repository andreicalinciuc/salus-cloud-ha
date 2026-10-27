"""Salus iT500 cloud responses in the format of the API, with the values a real single zone iT500 reported.

The real thermostat reported off and manual at once (A89 and A92 both 1), 60 °C for the zone 2 it does not have,
two numbers in its signal strength and an empty auto mode setpoint (A94).
"""

from typing import Any

DEVICE_ID = "123456789"
SERIAL = "STA00000000"
USER_ID = "987654"
NS = 'xmlns:ns1="http://arrayent.com/zamapi/"'

# Attributes of a single zone iT500: 17.5 °C, target 12.1 °C, off, batteries fine, gateway online
SINGLE_ZONE = {
    "A84": "1750",
    "A85": "1210",
    "A86": "1",
    "A87": "0",
    "A88": "0",
    "A89": "1",
    "A90": "0",
    "A91": "0",
    "A92": "1",
    "A93": "1210",
    "A94": "",
    "B84": "6000",
    "B85": "0",
    "B87": "0",
    "B89": "0",
    "C42": "0",
    "C45": "0",
    "F": "60",
    "S03": "0",
    "S06": "0",
    "S07": "0",
    "S09": "500",
    "S13": "11.7",
    "desc": "Home",
    "online": "1",
    "rfrssi": "-56 -1          ",
    "version": "1.5.2.0 (Mar 28 2017)",
    "Phone1": "+40700000000",
    "Rule": "45.0,26.0",
}


def attributes_xml(attributes: dict[str, Any], presence: str = "1") -> str:
    """Return a getDeviceAttributesWithValues response."""
    items = "".join(
        f"<attrList><id>{index}</id><name>{name}</name><displayName>{name}</displayName><device>true</device>"
        f"<value>{value}</value><updTime>1791514807067</updTime></attrList>"
        for index, (name, value) in enumerate(attributes.items(), start=300)
    )
    return (
        f"<ns1:getDeviceAttributesWithValuesResponse {NS}><typeId>1</typeId><typeName>IT500</typeName>"
        f"<presenceInfo>{presence}</presenceInfo><configurations><property>multiAttributeCapable</property>"
        f"<value>false</value></configurations>{items}</ns1:getDeviceAttributesWithValuesResponse>"
    )


def device_list_xml(*device_ids: str) -> str:
    """Return a getDeviceList response."""
    items = "".join(
        f"<devList><devId>{device_id}</devId><devName>{SERIAL}</devName><typeId>1</typeId>"
        f"<sleepMode>SHORT</sleepMode><appID>1097</appID><userID>{USER_ID}</userID></devList>"
        for device_id in device_ids
    )
    return f"<ns1:getDeviceListResponse {NS}>{items}</ns1:getDeviceListResponse>"


def set_xml(ret_code: int = 0) -> str:
    """Return a setMultiDeviceAttributes2 response."""
    return (
        f"<ns1:setMultiDeviceAttributes2Response {NS}><retCode>{ret_code}</retCode>"
        "</ns1:setMultiDeviceAttributes2Response>"
    )


def fault_xml(code: int, message: str = "Invalid security token.") -> str:
    """Return an error response."""
    return f"<ns1:requestFault {NS}><errorCode>{code}</errorCode><errorMsg>{message}</errorMsg></ns1:requestFault>"


def login_json(token: str = "token1") -> str:
    """Return a login response."""
    return f'{{"userId":{USER_ID},"securityToken":"{token}"}}'


LOGIN_REJECTED = '{"errorCode":101,"errorMessage":"Invalid login name or password."}'
