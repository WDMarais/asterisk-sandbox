from enum import Enum
from typing import Literal

from pydantic import BaseModel


class ChannelTechnology(str, Enum):
    PJSIP = "PJSIP"
    SIP = "SIP"
    LOCAL = "LOCAL"
    UNKNOWN_TECH = "UNKNOWN_TECH"
    INSCRUTABLE = "INSCRUTABLE"


class DeviceState(str, Enum):
    NOT_INUSE = "NOT_INUSE"
    INUSE = "INUSE"
    RINGING = "RINGING"
    RINGINUSE = "RINGINUSE"
    ONHOLD = "ONHOLD"
    UNAVAILABLE = "UNAVAILABLE"
    BUSY = "BUSY"
    INVALID = "INVALID"
    UNKNOWN = "UNKNOWN"


class RegistrationState(str, Enum):
    REGISTERED = "REGISTERED"
    UNREGISTERED = "UNREGISTERED"


# --- Channel parsing results ---

class ParsedChannel(BaseModel):
    technology: Literal[ChannelTechnology.PJSIP, ChannelTechnology.SIP]
    endpoint: str
    unique_id: str


class LocalChannel(BaseModel):
    technology: Literal[ChannelTechnology.LOCAL] = ChannelTechnology.LOCAL
    endpoint: str
    unique_id: str
    leg: int | None = None


class MalformedChannel(BaseModel):
    technology: ChannelTechnology
    error: Literal["MALFORMED_PARAMS"] = "MALFORMED_PARAMS"
    raw: str


class UnknownTechChannel(BaseModel):
    technology: Literal[ChannelTechnology.UNKNOWN_TECH] = ChannelTechnology.UNKNOWN_TECH
    raw: str


class InscrutableChannel(BaseModel):
    technology: Literal[ChannelTechnology.INSCRUTABLE] = ChannelTechnology.INSCRUTABLE
    raw: str


ChannelResult = ParsedChannel | LocalChannel | MalformedChannel | UnknownTechChannel | InscrutableChannel


# --- Device state parsing results ---

class KnownDeviceState(BaseModel):
    state: DeviceState
    registration: RegistrationState


class UnknownDeviceState(BaseModel):
    state: Literal[DeviceState.UNKNOWN] = DeviceState.UNKNOWN
    raw: str


DeviceStateResult = KnownDeviceState | UnknownDeviceState


# --- Parsers ---

_CHANNEL_TECHNOLOGIES: dict[str, ChannelTechnology] = {
    "PJSIP": ChannelTechnology.PJSIP,
    "SIP": ChannelTechnology.SIP,
    "Local": ChannelTechnology.LOCAL,
}


def parse_channel(raw: str | None) -> ChannelResult:
    if not raw:
        return InscrutableChannel(raw="")
    if "/" not in raw:
        return InscrutableChannel(raw=raw)

    tech_str, rest = raw.split("/", 1)

    if tech_str not in _CHANNEL_TECHNOLOGIES:
        return UnknownTechChannel(raw=raw)

    technology = _CHANNEL_TECHNOLOGIES[tech_str]

    if technology == ChannelTechnology.LOCAL:
        leg: int | None = None
        if ";" in rest:
            rest, leg_str = rest.rsplit(";", 1)
            try:
                leg = int(leg_str)
            except ValueError:
                return MalformedChannel(technology=technology, raw=raw)
        if "-" not in rest:
            return MalformedChannel(technology=technology, raw=raw)
        endpoint, unique_id = rest.rsplit("-", 1)
        return LocalChannel(endpoint=endpoint, unique_id=unique_id, leg=leg)

    if "-" not in rest:
        return MalformedChannel(technology=technology, raw=raw)
    endpoint, unique_id = rest.rsplit("-", 1)
    return ParsedChannel(technology=technology, endpoint=endpoint, unique_id=unique_id)


def parse_device_state(raw: str | None) -> DeviceStateResult:
    if not raw:
        return UnknownDeviceState(raw="")
    try:
        state = DeviceState(raw)
    except ValueError:
        return UnknownDeviceState(raw=raw)
    registration = (
        RegistrationState.UNREGISTERED
        if state == DeviceState.UNAVAILABLE
        else RegistrationState.REGISTERED
    )
    return KnownDeviceState(state=state, registration=registration)
