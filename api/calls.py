"""Runtime call tracking.

Accumulates AMI channel events per call (keyed on ``Uniqueid``) and runs the
pure ``classify_call_origin`` from :mod:`api.parsing` over the accumulated
sequence. This layer is stateful but I/O-free: it ingests already-parsed AMI
event dicts and returns the SSE events to publish, so it is testable without a
socket. The AMI client owns an instance, feeds it every event, and relays the
returned ``(event_type, payload)`` tuples through its subscriber fan-out.

A "call" here is a single channel leg. A logical call spans multiple legs
correlated by ``Linkedid`` (caller channel + agent channel); grouping by
linkedid is deferred — for now each leg is surfaced independently, which is
enough for a live-calls view and matches the spec's per-Uniqueid note.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from api.parsing import CallOrigin, classify_call_origin

logger = logging.getLogger(__name__)

# Events that create, mutate, or end a tracked call. Anything else (e.g.
# DeviceStateChange, login responses) is ignored by the tracker.
_TRACKED_EVENTS = frozenset({
    "Newchannel",
    "Newstate",
    "NewCallerid",
    "NewConnectedLine",
    "DialBegin",
    "DialEnd",
    "BridgeEnter",
    "BridgeLeave",
    "QueueCallerJoin",
    "QueueCallerLeave",
    "AgentCalled",
    "AgentConnect",
    "OriginateResponse",
    "Hangup",
})

# Publish event types emitted on the SSE stream.
CALL_STARTED = "call_started"
CALL_UPDATED = "call_updated"
CALL_ENDED = "call_ended"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Call:
    uniqueid: str
    linkedid: str | None = None
    channel: str | None = None
    caller_id_num: str | None = None
    caller_id_name: str | None = None
    extension: str | None = None  # dialed extension (AMI "Exten" field)
    state: str | None = None  # ChannelStateDesc: Down / Ring / Ringing / Up / ...
    origin: CallOrigin = CallOrigin.UNKNOWN
    started_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    events: list[dict[str, str]] = field(default_factory=list, repr=False)

    def snapshot(self) -> dict:
        """Public view — excludes the raw accumulated event list."""
        return {
            "uniqueid": self.uniqueid,
            "linkedid": self.linkedid,
            "channel": self.channel,
            "caller_id_num": self.caller_id_num,
            "caller_id_name": self.caller_id_name,
            "extension": self.extension,
            "state": self.state,
            "origin": self.origin,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
        }


def _present(value: str | None) -> bool:
    """An AMI field counts as present only when non-empty."""
    return bool(value)


@dataclass
class CallTracker:
    # Bare extension numbers the deployment knows about (e.g. {"6001", "6002"}).
    # Set by the owner from the current device list; injected into classification.
    known_endpoints: frozenset[str] = frozenset()
    # Uniqueids the broker originated itself (populated by /originate). Until that
    # endpoint exists this stays empty, so nothing is classified OUTBOUND yet.
    server_originated: set[str] = field(default_factory=set)
    calls: dict[str, Call] = field(default_factory=dict)

    def ingest(self, event: dict[str, str]) -> list[tuple[str, dict]]:
        """Apply one AMI event. Returns ``(event_type, payload)`` tuples to publish."""
        event_type = event.get("Event")
        # Positive allowlist: AMI is a firehose (VarSet, Newexten, FullyBooted,
        # ...). Untracked types are out of scope by design — silently ignored,
        # not logged per-event and never raised (raising would crash-loop the
        # event loop on every unrelated event).
        if event_type not in _TRACKED_EVENTS:
            return []

        uniqueid = event.get("Uniqueid")
        if not uniqueid:
            # Tracked event but identity unresolvable — the spec's §1.5 MALFORMED
            # case. Surface it rather than swallowing.
            logger.warning(
                "call tracker: %s event missing Uniqueid, cannot correlate: %r",
                event_type, event,
            )
            return []

        if event.get("Event") == "Hangup":
            return self._end_call(uniqueid, event)

        call = self.calls.get(uniqueid)
        created = call is None
        if created:
            call = Call(uniqueid=uniqueid)
            self.calls[uniqueid] = call

        before = call.snapshot()
        self._apply_fields(call, event)
        call.events.append(event)
        call.origin = classify_call_origin(
            call.events,
            is_server_originated=uniqueid in self.server_originated,
            known_endpoints=self.known_endpoints,
        )
        call.updated_at = _now()
        after = call.snapshot()

        if created:
            return [(CALL_STARTED, after)]
        # Compare ignoring the always-changing timestamp.
        if {k: v for k, v in after.items() if k != "updated_at"} != {
            k: v for k, v in before.items() if k != "updated_at"
        }:
            return [(CALL_UPDATED, after)]
        return []

    def _end_call(self, uniqueid: str, event: dict[str, str]) -> list[tuple[str, dict]]:
        call = self.calls.pop(uniqueid, None)
        self.server_originated.discard(uniqueid)
        if call is None:
            # Hangup for a call we never saw start — normal if we connected
            # mid-call (e.g. after an AMI reconnect), not an error.
            logger.debug("call tracker: Hangup for untracked call %s", uniqueid)
            return []
        call.state = "Hangup"
        call.updated_at = _now()
        payload = call.snapshot()
        payload["cause"] = event.get("Cause-txt") or event.get("Cause")
        return [(CALL_ENDED, payload)]

    @staticmethod
    def _apply_fields(call: Call, event: dict[str, str]) -> None:
        # Set-if-present so a later event with an empty field doesn't wipe a
        # value an earlier event established.
        if _present(event.get("Channel")):
            call.channel = event["Channel"]
        if _present(event.get("Linkedid")):
            call.linkedid = event["Linkedid"]
        if _present(event.get("CallerIDNum")):
            call.caller_id_num = event["CallerIDNum"]
        if _present(event.get("CallerIDName")):
            call.caller_id_name = event["CallerIDName"]
        if _present(event.get("Exten")):
            call.extension = event["Exten"]
        if _present(event.get("ChannelStateDesc")):
            call.state = event["ChannelStateDesc"]
