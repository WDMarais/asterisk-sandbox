import pytest

from api.parsing import (
    AgentState,
    ChannelTechnology,
    DeviceState,
    InscrutableChannel,
    KnownDeviceState,
    LocalChannel,
    MalformedChannel,
    ParsedChannel,
    RegistrationState,
    UnknownDeviceState,
    UnknownTechChannel,
    agent_state_from_device_state,
    is_blocked_intentional_transition,
    parse_channel,
    parse_device_state,
    transition_agent_state,
)


# --- parse_channel ---

class TestParseChannel:
    def test_pjsip_happy_path(self):
        r = parse_channel("PJSIP/6001-0000000a")
        assert isinstance(r, ParsedChannel)
        assert r.technology == ChannelTechnology.PJSIP
        assert r.endpoint == "6001"
        assert r.unique_id == "0000000a"

    def test_sip_happy_path(self):
        r = parse_channel("SIP/6001-0000000a")
        assert isinstance(r, ParsedChannel)
        assert r.technology == ChannelTechnology.SIP
        assert r.endpoint == "6001"
        assert r.unique_id == "0000000a"

    def test_local_leg_1(self):
        r = parse_channel("Local/6001@from-internal-0000000a;1")
        assert isinstance(r, LocalChannel)
        assert r.endpoint == "6001@from-internal"
        assert r.unique_id == "0000000a"
        assert r.leg == 1

    def test_local_leg_2(self):
        r = parse_channel("Local/6001@from-internal-0000000a;2")
        assert isinstance(r, LocalChannel)
        assert r.leg == 2

    def test_pjsip_missing_unique_id(self):
        r = parse_channel("PJSIP/6001")
        assert isinstance(r, MalformedChannel)
        assert r.technology == ChannelTechnology.PJSIP
        assert r.error == "MALFORMED_PARAMS"
        assert r.raw == "PJSIP/6001"

    def test_unknown_technology(self):
        r = parse_channel("DAHDI/1-0000000a")
        assert isinstance(r, UnknownTechChannel)
        assert r.technology == ChannelTechnology.UNKNOWN_TECH
        assert r.raw == "DAHDI/1-0000000a"

    def test_inscrutable_no_slash(self):
        r = parse_channel("notavalidstring")
        assert isinstance(r, InscrutableChannel)
        assert r.technology == ChannelTechnology.INSCRUTABLE

    def test_inscrutable_empty_string(self):
        r = parse_channel("")
        assert isinstance(r, InscrutableChannel)
        assert r.raw == ""

    def test_inscrutable_none(self):
        r = parse_channel(None)
        assert isinstance(r, InscrutableChannel)
        assert r.raw == ""


# --- parse_device_state ---

class TestParseDeviceState:
    @pytest.mark.parametrize("raw,expected", [
        ("NOT_INUSE",   DeviceState.NOT_INUSE),
        ("INUSE",       DeviceState.INUSE),
        ("RINGING",     DeviceState.RINGING),
        ("RINGINUSE",   DeviceState.RINGINUSE),
        ("ONHOLD",      DeviceState.ONHOLD),
        ("UNAVAILABLE", DeviceState.UNAVAILABLE),
        ("BUSY",        DeviceState.BUSY),
        ("INVALID",     DeviceState.INVALID),
    ])
    def test_known_states(self, raw, expected):
        r = parse_device_state(raw)
        assert isinstance(r, KnownDeviceState)
        assert r.state == expected

    def test_unknown_custom_string(self):
        r = parse_device_state("CUSTOM_THING")
        assert isinstance(r, UnknownDeviceState)
        assert r.raw == "CUSTOM_THING"

    def test_unknown_empty_string(self):
        r = parse_device_state("")
        assert isinstance(r, UnknownDeviceState)
        assert r.raw == ""

    def test_unknown_none(self):
        r = parse_device_state(None)
        assert isinstance(r, UnknownDeviceState)

    def test_unavailable_derives_unregistered(self):
        r = parse_device_state("UNAVAILABLE")
        assert isinstance(r, KnownDeviceState)
        assert r.registration == RegistrationState.UNREGISTERED

    @pytest.mark.parametrize("raw", [
        "NOT_INUSE", "INUSE", "RINGING", "RINGINUSE", "ONHOLD", "BUSY", "INVALID",
    ])
    def test_non_unavailable_derives_registered(self, raw):
        r = parse_device_state(raw)
        assert isinstance(r, KnownDeviceState)
        assert r.registration == RegistrationState.REGISTERED


# --- transition_agent_state ---

class TestTransitionAgentState:
    @pytest.mark.parametrize("current,proposed", [
        (AgentState.AVAILABLE,    AgentState.RINGING_IN),
        (AgentState.AVAILABLE,    AgentState.RINGING_OUT),
        (AgentState.AVAILABLE,    AgentState.IN_CALL),
        (AgentState.AVAILABLE,    AgentState.DND),
        (AgentState.AVAILABLE,    AgentState.OFFLINE),
        (AgentState.RINGING_IN,   AgentState.IN_CALL),
        (AgentState.RINGING_IN,   AgentState.AVAILABLE),
        (AgentState.RINGING_OUT,  AgentState.IN_CALL),
        (AgentState.RINGING_OUT,  AgentState.AVAILABLE),
        (AgentState.IN_CALL,      AgentState.ON_HOLD),
        (AgentState.IN_CALL,      AgentState.AVAILABLE),
        (AgentState.IN_CALL,      AgentState.DND_IN_CALL),
        (AgentState.IN_CALL,      AgentState.OFFLINE),
        (AgentState.ON_HOLD,      AgentState.IN_CALL),
        (AgentState.ON_HOLD,      AgentState.AVAILABLE),
        (AgentState.ON_HOLD,      AgentState.DND_ON_HOLD),
        (AgentState.ON_HOLD,      AgentState.OFFLINE),
        (AgentState.DND,          AgentState.AVAILABLE),
        (AgentState.DND,          AgentState.OFFLINE),
        (AgentState.DND_IN_CALL,  AgentState.DND),
        (AgentState.DND_ON_HOLD,  AgentState.DND_IN_CALL),
        (AgentState.DND_ON_HOLD,  AgentState.DND),
        (AgentState.OFFLINE,      AgentState.AVAILABLE),
    ])
    def test_allowed_transitions(self, current, proposed):
        assert transition_agent_state(current, proposed) == proposed

    @pytest.mark.parametrize("current,proposed", [
        (AgentState.IN_CALL,     AgentState.RINGING_IN),
        (AgentState.OFFLINE,     AgentState.IN_CALL),
        (AgentState.DND_IN_CALL, AgentState.AVAILABLE),
    ])
    def test_invalid_transitions_return_current(self, current, proposed):
        assert transition_agent_state(current, proposed) == current

    def test_same_state_is_noop(self):
        for state in AgentState:
            assert transition_agent_state(state, state) == state


class TestBlockedIntentionalTransitions:
    def test_in_call_to_offline_is_blocked(self):
        assert is_blocked_intentional_transition(AgentState.IN_CALL, AgentState.OFFLINE)

    def test_on_hold_to_offline_is_blocked(self):
        assert is_blocked_intentional_transition(AgentState.ON_HOLD, AgentState.OFFLINE)

    def test_available_to_offline_is_not_blocked(self):
        assert not is_blocked_intentional_transition(AgentState.AVAILABLE, AgentState.OFFLINE)


# --- agent_state_from_device_state ---

class TestAgentStateFromDeviceState:
    def test_unavailable_from_available_goes_offline(self):
        assert agent_state_from_device_state(DeviceState.UNAVAILABLE, AgentState.AVAILABLE) == AgentState.OFFLINE

    def test_unavailable_from_in_call_goes_offline(self):
        # Forced offline (browser crash) — not blocked at AMI level
        assert agent_state_from_device_state(DeviceState.UNAVAILABLE, AgentState.IN_CALL) == AgentState.OFFLINE

    def test_unavailable_from_on_hold_goes_offline(self):
        assert agent_state_from_device_state(DeviceState.UNAVAILABLE, AgentState.ON_HOLD) == AgentState.OFFLINE

    def test_not_inuse_from_in_call_goes_available(self):
        assert agent_state_from_device_state(DeviceState.NOT_INUSE, AgentState.IN_CALL) == AgentState.AVAILABLE

    def test_not_inuse_from_dnd_in_call_auto_transitions_to_dnd(self):
        assert agent_state_from_device_state(DeviceState.NOT_INUSE, AgentState.DND_IN_CALL) == AgentState.DND

    def test_not_inuse_from_dnd_on_hold_auto_transitions_to_dnd(self):
        assert agent_state_from_device_state(DeviceState.NOT_INUSE, AgentState.DND_ON_HOLD) == AgentState.DND

    def test_not_inuse_from_offline_goes_available(self):
        assert agent_state_from_device_state(DeviceState.NOT_INUSE, AgentState.OFFLINE) == AgentState.AVAILABLE

    def test_inuse_from_ringing_in_goes_in_call(self):
        assert agent_state_from_device_state(DeviceState.INUSE, AgentState.RINGING_IN) == AgentState.IN_CALL

    def test_inuse_from_available_goes_in_call(self):
        # Auto-answer path — no RINGING step
        assert agent_state_from_device_state(DeviceState.INUSE, AgentState.AVAILABLE) == AgentState.IN_CALL

    def test_ringing_from_available_goes_ringing_in(self):
        assert agent_state_from_device_state(DeviceState.RINGING, AgentState.AVAILABLE) == AgentState.RINGING_IN

    def test_onhold_from_in_call_goes_on_hold(self):
        assert agent_state_from_device_state(DeviceState.ONHOLD, AgentState.IN_CALL) == AgentState.ON_HOLD

    def test_unknown_device_state_is_noop(self):
        assert agent_state_from_device_state(DeviceState.UNKNOWN, AgentState.AVAILABLE) == AgentState.AVAILABLE
