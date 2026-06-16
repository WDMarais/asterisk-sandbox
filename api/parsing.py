import logging
from enum import Enum
from typing import Literal

from pydantic import BaseModel

logger = logging.getLogger(__name__)


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


# --- Agent combined state FSM ---

class AgentState(str, Enum):
    AVAILABLE    = "AVAILABLE"
    RINGING_IN   = "RINGING_IN"
    RINGING_OUT  = "RINGING_OUT"
    IN_CALL      = "IN_CALL"
    ON_HOLD      = "ON_HOLD"
    DND          = "DND"
    DND_IN_CALL  = "DND_IN_CALL"
    DND_ON_HOLD  = "DND_ON_HOLD"
    OFFLINE      = "OFFLINE"


_ALLOWED_TRANSITIONS: dict[AgentState, frozenset[AgentState]] = {
    AgentState.AVAILABLE:   frozenset({AgentState.RINGING_IN, AgentState.RINGING_OUT,
                                        AgentState.IN_CALL, AgentState.DND, AgentState.OFFLINE}),
    AgentState.RINGING_IN:  frozenset({AgentState.IN_CALL, AgentState.AVAILABLE}),
    AgentState.RINGING_OUT: frozenset({AgentState.IN_CALL, AgentState.AVAILABLE}),
    AgentState.IN_CALL:     frozenset({AgentState.ON_HOLD, AgentState.AVAILABLE,
                                        AgentState.DND_IN_CALL, AgentState.OFFLINE}),
    AgentState.ON_HOLD:     frozenset({AgentState.IN_CALL, AgentState.AVAILABLE,
                                        AgentState.DND_ON_HOLD, AgentState.OFFLINE}),
    AgentState.DND:         frozenset({AgentState.AVAILABLE, AgentState.OFFLINE}),
    AgentState.DND_IN_CALL: frozenset({AgentState.DND}),
    AgentState.DND_ON_HOLD: frozenset({AgentState.DND_IN_CALL, AgentState.DND}),
    AgentState.OFFLINE:     frozenset({AgentState.AVAILABLE}),
}

# Transitions that are explicitly blocked (not just absent from the table).
_BLOCKED_TRANSITIONS: frozenset[tuple[AgentState, AgentState]] = frozenset({
    (AgentState.IN_CALL,  AgentState.OFFLINE),
    (AgentState.ON_HOLD,  AgentState.OFFLINE),
})


def transition_agent_state(current: AgentState, proposed: AgentState) -> AgentState:
    """Apply a transition if allowed. Caller is responsible for checking blocked
    transitions when the request is intentional (UI/API boundary).
    AMI-driven transitions bypass the blocked set — a forced offline (browser crash,
    network drop) must still land in OFFLINE regardless of call state.
    """
    if current == proposed:
        return current
    if proposed not in _ALLOWED_TRANSITIONS.get(current, frozenset()):
        logger.warning("invalid transition %s → %s", current, proposed)
        return current
    return proposed


def is_blocked_intentional_transition(current: AgentState, proposed: AgentState) -> bool:
    """Returns True for transitions the agent is not allowed to request intentionally.
    Use this at the API/UI boundary, not in AMI event handling.
    """
    return (current, proposed) in _BLOCKED_TRANSITIONS


# --- Call origin classification ---

class CallOrigin(str, Enum):
    OUTBOUND = "OUTBOUND"
    QUEUE    = "QUEUE"
    INTERNAL = "INTERNAL"
    UNKNOWN  = "UNKNOWN"


def classify_call_origin(
    events: list[dict[str, str]],
    is_server_originated: bool,
    known_endpoints: frozenset[str],
) -> CallOrigin:
    if is_server_originated:
        if any(e.get("Event") == "OriginateResponse" for e in events):
            return CallOrigin.OUTBOUND
        return CallOrigin.UNKNOWN

    if any("Queue" in e for e in events):
        return CallOrigin.QUEUE

    caller_ids = {e["CallerIDNum"] for e in events if "CallerIDNum" in e}
    destinations = {e["Exten"] for e in events if "Exten" in e}
    if caller_ids & known_endpoints and destinations & known_endpoints:
        return CallOrigin.INTERNAL

    return CallOrigin.UNKNOWN


def agent_state_from_device_state(
    device_state: DeviceState, current: AgentState
) -> AgentState:
    """Derive a proposed agent state from a raw device state change.

    Cannot distinguish RINGING_IN from RINGING_OUT — that requires Newchannel
    events tracked separately. RINGING always proposes RINGING_IN for now.
    """
    match device_state:
        case DeviceState.UNAVAILABLE:
            proposed = AgentState.OFFLINE
        case DeviceState.NOT_INUSE:
            # DND_IN_CALL and DND_ON_HOLD auto-transition to DND when the call ends.
            if current in (AgentState.DND_IN_CALL, AgentState.DND_ON_HOLD):
                proposed = AgentState.DND
            else:
                proposed = AgentState.AVAILABLE
        case DeviceState.INUSE | DeviceState.BUSY:
            proposed = AgentState.IN_CALL
        case DeviceState.RINGING | DeviceState.RINGINUSE:
            proposed = AgentState.RINGING_IN
        case DeviceState.ONHOLD:
            proposed = AgentState.ON_HOLD
        case _:
            return current
    return transition_agent_state(current, proposed)
