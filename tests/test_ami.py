import asyncio
import json

import pytest

from api.ami import AmiClient
from api.parsing import CallOrigin


@pytest.fixture
def client():
    return AmiClient(host="localhost", port=5038, username="u", secret="s")


class FakeWriter:
    """Captures bytes written; satisfies the StreamWriter bits originate uses."""

    def __init__(self):
        self.data = b""

    def write(self, b: bytes) -> None:
        self.data += b

    async def drain(self) -> None:
        pass


class TestOriginate:
    def test_sends_action_and_tags_server_originated(self, client):
        client._writer = FakeWriter()
        asyncio.run(client.originate(
            channel="PJSIP/6001", exten="6002", context="internal", channel_id="cid1",
        ))
        assert "cid1" in client.tracker.server_originated
        sent = client._writer.data.decode()
        assert "Action: Originate\r\n" in sent
        assert "Channel: PJSIP/6001\r\n" in sent
        assert "Exten: 6002\r\n" in sent
        assert "Context: internal\r\n" in sent
        assert "ChannelId: cid1\r\n" in sent
        assert "Async: true\r\n" in sent
        assert sent.endswith("\r\n\r\n")

    def test_originate_unconnected_raises(self, client):
        with pytest.raises(RuntimeError):
            asyncio.run(client.originate(
                channel="PJSIP/6001", exten="6002", context="internal", channel_id="x",
            ))

    def test_originated_call_classifies_outbound(self, client):
        client._writer = FakeWriter()
        asyncio.run(client.originate(
            channel="PJSIP/6001", exten="6002", context="internal", channel_id="cid1",
        ))
        client.tracker.known_endpoints = frozenset({"6001", "6002"})
        # Channel appears first — server-originated but no OriginateResponse yet -> deferred.
        client.tracker.ingest({
            "Event": "Newchannel", "Uniqueid": "cid1",
            "Channel": "PJSIP/6001-cid1", "CallerIDNum": "6001", "Exten": "6002",
        })
        assert client.tracker.calls["cid1"].origin == CallOrigin.UNKNOWN
        # OriginateResponse confirms it -> OUTBOUND.
        client.tracker.ingest({
            "Event": "OriginateResponse", "Uniqueid": "cid1",
            "Channel": "PJSIP/6001-cid1", "Response": "Success",
        })
        assert client.tracker.calls["cid1"].origin == CallOrigin.OUTBOUND


class TestSubscription:
    def test_subscribe_returns_queue(self, client):
        q = client.subscribe()
        assert isinstance(q, asyncio.Queue)

    def test_publish_delivers_to_subscriber(self, client):
        q = client.subscribe()
        client._publish("agent_state_changed", {"device": "PJSIP/6001", "state": "AVAILABLE", "previous": "OFFLINE"})
        assert not q.empty()

    def test_publish_chunk_format(self, client):
        q = client.subscribe()
        client._publish("agent_state_changed", {"device": "PJSIP/6001", "state": "AVAILABLE", "previous": "OFFLINE"})
        chunk = q.get_nowait()
        assert chunk.startswith("event: agent_state_changed\n")
        assert "data: " in chunk
        assert chunk.endswith("\n\n")
        payload = json.loads(chunk.split("data: ", 1)[1].strip())
        assert payload["device"] == "PJSIP/6001"
        assert payload["state"] == "AVAILABLE"
        assert payload["previous"] == "OFFLINE"

    def test_publish_delivers_to_multiple_subscribers(self, client):
        q1 = client.subscribe()
        q2 = client.subscribe()
        client._publish("agent_state_changed", {"device": "PJSIP/6001", "state": "IN_CALL", "previous": "RINGING_IN"})
        assert not q1.empty()
        assert not q2.empty()

    def test_unsubscribe_stops_delivery(self, client):
        q = client.subscribe()
        client.unsubscribe(q)
        client._publish("agent_state_changed", {"device": "PJSIP/6001", "state": "AVAILABLE", "previous": "OFFLINE"})
        assert q.empty()

    def test_unsubscribe_unknown_queue_is_noop(self, client):
        q: asyncio.Queue[str] = asyncio.Queue()
        client.unsubscribe(q)  # should not raise
