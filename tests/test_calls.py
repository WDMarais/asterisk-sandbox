import logging

import pytest

from api.calls import CALL_ENDED, CALL_STARTED, CALL_UPDATED, CallTracker
from api.parsing import CallOrigin


@pytest.fixture
def tracker():
    return CallTracker(known_endpoints=frozenset({"6001", "6002"}))


def _newchannel(uniqueid="0000000a", caller="6001", exten="6002", **extra):
    event = {
        "Event": "Newchannel",
        "Channel": f"PJSIP/{caller}-{uniqueid}",
        "ChannelStateDesc": "Ring",
        "CallerIDNum": caller,
        "Exten": exten,
        "Uniqueid": uniqueid,
        "Linkedid": uniqueid,
    }
    event.update(extra)
    return event


class TestLifecycle:
    def test_newchannel_creates_call(self, tracker):
        out = tracker.ingest(_newchannel())
        assert "0000000a" in tracker.calls
        assert out == [(CALL_STARTED, tracker.calls["0000000a"].snapshot())]

    def test_snapshot_uses_extension_not_exten(self, tracker):
        tracker.ingest(_newchannel(exten="6002"))
        snap = tracker.calls["0000000a"].snapshot()
        assert snap["extension"] == "6002"
        assert "exten" not in snap

    def test_newstate_updates_state_and_emits_update(self, tracker):
        tracker.ingest(_newchannel())
        out = tracker.ingest({
            "Event": "Newstate",
            "Channel": "PJSIP/6001-0000000a",
            "ChannelStateDesc": "Up",
            "Uniqueid": "0000000a",
        })
        assert tracker.calls["0000000a"].state == "Up"
        assert out[0][0] == CALL_UPDATED
        assert out[0][1]["state"] == "Up"

    def test_no_update_emitted_when_public_state_unchanged(self, tracker):
        tracker.ingest(_newchannel())
        # A tracked event that touches no public field should not emit.
        out = tracker.ingest({
            "Event": "BridgeEnter",
            "Uniqueid": "0000000a",
        })
        assert out == []

    def test_hangup_removes_call_and_emits_ended(self, tracker):
        tracker.ingest(_newchannel())
        out = tracker.ingest({
            "Event": "Hangup",
            "Channel": "PJSIP/6001-0000000a",
            "Uniqueid": "0000000a",
            "Cause": "16",
            "Cause-txt": "Normal Clearing",
        })
        assert "0000000a" not in tracker.calls
        assert out[0][0] == CALL_ENDED
        assert out[0][1]["state"] == "Hangup"
        assert out[0][1]["cause"] == "Normal Clearing"

    def test_empty_field_does_not_overwrite_established_value(self, tracker):
        tracker.ingest(_newchannel(exten="6002"))
        tracker.ingest({
            "Event": "Newstate",
            "ChannelStateDesc": "Up",
            "Exten": "",  # empty must not wipe the earlier extension
            "Uniqueid": "0000000a",
        })
        assert tracker.calls["0000000a"].extension == "6002"


class TestOriginClassification:
    def test_internal_call(self, tracker):
        out = tracker.ingest(_newchannel(caller="6001", exten="6002"))
        assert out[0][1]["origin"] == CallOrigin.INTERNAL

    def test_queue_call(self, tracker):
        out = tracker.ingest({
            "Event": "QueueCallerJoin",
            "Queue": "support",
            "Channel": "PJSIP/0821234567-0000000b",
            "CallerIDNum": "0821234567",
            "Uniqueid": "0000000b",
        })
        assert out[0][1]["origin"] == CallOrigin.QUEUE

    def test_outbound_requires_server_originated_flag(self, tracker):
        tracker.server_originated.add("0000000c")
        out = tracker.ingest({
            "Event": "OriginateResponse",
            "Response": "Success",
            "Channel": "PJSIP/6001-0000000c",
            "Uniqueid": "0000000c",
        })
        assert out[0][1]["origin"] == CallOrigin.OUTBOUND

    def test_unknown_when_endpoints_not_known(self, tracker):
        out = tracker.ingest(_newchannel(caller="0820000000", exten="0119999999"))
        assert out[0][1]["origin"] == CallOrigin.UNKNOWN

    def test_hangup_clears_server_originated(self, tracker):
        tracker.server_originated.add("0000000c")
        tracker.ingest({
            "Event": "OriginateResponse",
            "Channel": "PJSIP/6001-0000000c",
            "Uniqueid": "0000000c",
        })
        tracker.ingest({"Event": "Hangup", "Uniqueid": "0000000c"})
        assert "0000000c" not in tracker.server_originated


class TestIgnoredAndMalformed:
    def test_untracked_event_ignored_silently(self, tracker, caplog):
        with caplog.at_level(logging.WARNING):
            out = tracker.ingest({"Event": "VarSet", "Uniqueid": "0000000a"})
        assert out == []
        assert tracker.calls == {}
        assert caplog.records == []

    def test_tracked_event_missing_uniqueid_warns(self, tracker, caplog):
        with caplog.at_level(logging.WARNING):
            out = tracker.ingest({"Event": "Hangup", "Channel": "PJSIP/6001-x"})
        assert out == []
        assert any("missing Uniqueid" in r.getMessage() for r in caplog.records)

    def test_hangup_for_untracked_call_is_noop(self, tracker):
        out = tracker.ingest({"Event": "Hangup", "Uniqueid": "nope"})
        assert out == []
