"""An iT500 as the integration sees it: its attributes decoded into zones, modes and system values."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

# Zone attributes are the zone letter plus a number, e.g. A85 "CH1 Current Setpoint (x 0.01C)"
ROOM_TEMPERATURE = "84"
SETPOINT = "85"
RELAY = "87"
TEMPORARY_HOLD = "88"  # 0 schedule, 1 temporary hold (the schedule continues at its next change)
OFF = "89"
FROST_ACTIVE = "90"
MANUAL = "92"

BATTERY = "S03"  # "0" while the batteries are fine
SYSTEM_TYPE = "S06"  # 0 CH1, 1 CH1 + CH2 (iT300TX receiver), 2 CH1 + hot water
FIRMWARE = "S13"
ONLINE = "online"
RSSI = "rfrssi"  # e.g. "-56 -1"
DESCRIPTION = "desc"
HOT_WATER_MODE = "C42"
HOT_WATER_ON = "C45"
# "Turn On Refresh Mode for X Seconds (Recommend X=60)": the gateway wakes the thermostat, which then takes
# commands at once and reports all its values within seconds
REFRESH = "F"
REFRESH_SECONDS = "60"

SYSTEM_TWO_ZONES = "1"
SYSTEM_HOT_WATER = "2"
# C42 "Hot Water Mode(Auto, Once, On or Off)"
HOT_WATER_MODES = ("auto", "once", "on", "off")
# A broken cloud session reports 32 °C / 32 °C (salusfy issues #9 and #31); such a reading is never shown
BOGUS_READING = "3200"


class Mode(StrEnum):
    """Operating mode of a heating zone; the presets of its climate entity besides off."""

    OFF = "off"
    SCHEDULE = "schedule"
    TEMPORARY_HOLD = "temporary_hold"
    MANUAL = "manual"


@dataclass(frozen=True)
class Zone:
    """Heating zone: 1 is the thermostat itself, 2 an iT300TX receiver."""

    number: int
    prefix: str

    def attribute(self, suffix: str) -> str:
        """Return the attribute of the zone, e.g. "B85" for the setpoint of zone 2."""
        return f"{self.prefix}{suffix}"


ZONE_1 = Zone(1, "A")
ZONE_2 = Zone(2, "B")


def _centi(value: str | None) -> float | None:
    if value is None or not value.lstrip("-").isdigit():
        return None
    return int(value) / 100


def _flag(value: str | None) -> bool | None:
    return None if value in (None, "") else value == "1"


@dataclass(frozen=True, kw_only=True)
class It500Thermostat:
    """An iT500 of the account with its attributes (commanded values shown until it reports them)."""

    id: str
    serial: str
    attributes: dict[str, str] = field(default_factory=dict)
    # Whether its attributes were read recently
    fresh: bool = False

    @property
    def unique_id(self) -> str:
        """Return the identifier of the device in Home Assistant."""
        return f"it500_{self.id}"

    @property
    def name(self) -> str:
        """Return the name given in the Salus iT500 app."""
        return self.attributes.get(DESCRIPTION) or self.serial or "iT500"

    @property
    def is_thermostat(self) -> bool:
        """Return whether the device reports a heating zone."""
        return any(self.attributes.get(ZONE_1.attribute(suffix)) for suffix in (ROOM_TEMPERATURE, SETPOINT))

    @property
    def zones(self) -> list[Zone]:
        """Return the heating zones; a single zone system reports meaningless zone 2 values (60 °C)."""
        return [ZONE_1, ZONE_2] if self.attributes.get(SYSTEM_TYPE) == SYSTEM_TWO_ZONES else [ZONE_1]

    @property
    def has_hot_water(self) -> bool:
        """Return whether the thermostat also controls hot water."""
        return self.attributes.get(SYSTEM_TYPE) == SYSTEM_HOT_WATER

    def room_temperature(self, zone: Zone) -> float | None:
        """Return the measured temperature of a zone in °C (the API reports 0.01 °C whatever the display unit)."""
        return _centi(self.attributes.get(zone.attribute(ROOM_TEMPERATURE)))

    def setpoint(self, zone: Zone) -> float | None:
        """Return the target temperature of a zone in °C."""
        return _centi(self.attributes.get(zone.attribute(SETPOINT)))

    def heating(self, zone: Zone) -> bool | None:
        """Return whether the boiler relay of a zone is on."""
        return _flag(self.attributes.get(zone.attribute(RELAY)))

    def frost_active(self, zone: Zone) -> bool | None:
        """Return whether frost protection of a zone is active."""
        return _flag(self.attributes.get(zone.attribute(FROST_ACTIVE)))

    def mode(self, zone: Zone) -> Mode:
        """Return the mode of a zone; the off flag wins, a thermostat can report off and manual at once."""
        if _flag(self.attributes.get(zone.attribute(OFF))):
            return Mode.OFF
        if _flag(self.attributes.get(zone.attribute(MANUAL))):
            return Mode.MANUAL
        if _flag(self.attributes.get(zone.attribute(TEMPORARY_HOLD))):
            return Mode.TEMPORARY_HOLD
        return Mode.SCHEDULE

    @property
    def battery_low(self) -> bool | None:
        """Return whether the thermostat reports low batteries."""
        value = self.attributes.get(BATTERY)
        return None if value in (None, "") else value != "0"

    @property
    def online(self) -> bool | None:
        """Return whether the gateway is connected to the cloud."""
        return _flag(self.attributes.get(ONLINE))

    @property
    def rssi(self) -> int | None:
        """Return the radio signal between thermostat and gateway in dBm."""
        token = (self.attributes.get(RSSI) or "").split()[:1]
        return int(token[0]) if token and token[0].lstrip("-").isdigit() else None

    @property
    def hot_water_mode(self) -> str | None:
        """Return the hot water mode: auto, once, on or off."""
        value = self.attributes.get(HOT_WATER_MODE) or ""
        return HOT_WATER_MODES[int(value)] if value.isdigit() and int(value) < len(HOT_WATER_MODES) else None

    @property
    def hot_water_on(self) -> bool | None:
        """Return whether hot water is being heated."""
        return _flag(self.attributes.get(HOT_WATER_ON))


def is_plausible(attributes: dict[str, str]) -> bool:
    """Return False for the reading of a broken cloud session."""
    return not (
        attributes.get(ZONE_1.attribute(ROOM_TEMPERATURE)) == BOGUS_READING
        and attributes.get(ZONE_1.attribute(SETPOINT)) == BOGUS_READING
    )


def setpoint_writes(zone: Zone, temperature: float) -> list[tuple[str, str]]:
    """Return the write of a target temperature, on the 0.1 °C steps of the thermostat."""
    return [(zone.attribute(SETPOINT), str(round(temperature * 10) * 10))]


def mode_writes(attributes: dict[str, str], zone: Zone, mode: Mode) -> list[tuple[str, str]]:
    """Return the writes selecting a mode, skipping flags that already have their value.

    Leaving off clears the off flag last, so the zone resumes in the new mode. A temporary hold does not end by
    clearing its flag alone (salus-it500-cloud): the flag is cleared while the zone is in manual mode.
    """
    off, manual, hold = zone.attribute(OFF), zone.attribute(MANUAL), zone.attribute(TEMPORARY_HOLD)
    wanted = {
        Mode.OFF: [(off, "1")],
        Mode.MANUAL: [(manual, "1"), (off, "0")],
        Mode.TEMPORARY_HOLD: [(manual, "0"), (hold, "1"), (off, "0")],
        Mode.SCHEDULE: [(manual, "0"), (hold, "0"), (off, "0")],
    }[mode]
    writes = [(name, value) for name, value in wanted if attributes.get(name) != value]
    if mode is Mode.SCHEDULE and attributes.get(hold) == "1":
        writes = [(manual, "1"), (hold, "0"), (manual, "0"), *(write for write in writes if write[0] == off)]
    return writes


def turn_on_writes(zone: Zone) -> list[tuple[str, str]]:
    """Return the write turning a zone on again: it resumes the mode its other flags still show."""
    return [(zone.attribute(OFF), "0")]


def hot_water_mode_writes(mode: str) -> list[tuple[str, str]]:
    """Return the write of a hot water mode."""
    return [(HOT_WATER_MODE, str(HOT_WATER_MODES.index(mode)))]
