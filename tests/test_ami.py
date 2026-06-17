import asyncio
import json

import pytest

from api.ami import AmiClient


@pytest.fixture
def client():
    return AmiClient(host="localhost", port=5038, username="u", secret="s")


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
