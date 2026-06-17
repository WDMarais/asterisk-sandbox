import asyncio
import contextlib
import json
import logging
from dataclasses import dataclass, field

from api.parsing import (
    AgentState,
    DeviceStateResult,
    KnownDeviceState,
    agent_state_from_device_state,
    parse_device_state,
)

logger = logging.getLogger(__name__)

_RECONNECT_BACKOFF_INITIAL = 1.0
_RECONNECT_BACKOFF_MAX = 60.0


@dataclass
class AmiClient:
    host: str
    port: int
    username: str
    secret: str
    device_states: dict[str, DeviceStateResult] = field(default_factory=dict)
    agent_states: dict[str, AgentState] = field(default_factory=dict)
    _reader: asyncio.StreamReader | None = field(default=None, repr=False)
    _writer: asyncio.StreamWriter | None = field(default=None, repr=False)
    _subscribers: list[asyncio.Queue[str]] = field(default_factory=list, repr=False)

    def subscribe(self) -> asyncio.Queue[str]:
        q: asyncio.Queue[str] = asyncio.Queue()
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[str]) -> None:
        try:
            self._subscribers.remove(q)
        except ValueError:
            pass

    def _publish(self, event_type: str, payload: dict) -> None:
        chunk = f"event: {event_type}\ndata: {json.dumps(payload)}\n\n"
        for q in self._subscribers:
            q.put_nowait(chunk)

    async def _do_connect(self) -> None:
        self._reader, self._writer = await asyncio.open_connection(self.host, self.port)
        greeting = await self._reader.readline()
        logger.info("AMI: %s", greeting.decode().strip())
        await self._login()
        await self._request_device_state_list()

    async def connect(self) -> None:
        await self._do_connect()
        asyncio.create_task(self._event_loop())

    async def _reconnect(self) -> None:
        if self._writer:
            self._writer.close()
            with contextlib.suppress(Exception):
                await self._writer.wait_closed()
        await self._do_connect()

    async def _login(self) -> None:
        self._writer.write(
            f"Action: Login\r\nUsername: {self.username}\r\nSecret: {self.secret}\r\n\r\n"
            .encode()
        )
        await self._writer.drain()
        response = await self._read_block()
        if response.get("Response") != "Success":
            raise RuntimeError(f"AMI login failed: {response}")
        logger.info("AMI authenticated as %s", self.username)

    async def _read_block(self) -> dict[str, str]:
        block: dict[str, str] = {}
        while True:
            line = await self._reader.readline()
            if not line:
                raise ConnectionError("AMI connection closed")
            text = line.decode(errors="replace").rstrip("\r\n")
            if not text:
                break
            if ": " in text:
                key, _, value = text.partition(": ")
                block[key] = value
        return block

    async def _request_device_state_list(self) -> None:
        self._writer.write(b"Action: DeviceStateList\r\n\r\n")
        await self._writer.drain()

    async def _event_loop(self) -> None:
        backoff = _RECONNECT_BACKOFF_INITIAL
        while True:
            try:
                block = await self._read_block()
                backoff = _RECONNECT_BACKOFF_INITIAL
            except Exception:
                logger.exception("AMI connection lost — reconnecting in %.0fs", backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, _RECONNECT_BACKOFF_MAX)
                try:
                    await self._reconnect()
                    logger.info("AMI reconnected")
                except Exception:
                    logger.exception("AMI reconnect failed")
                continue

            if block.get("Event") == "DeviceStateChange":
                device = block.get("Device", "")
                if not device or not device.startswith(("PJSIP/", "SIP/")):
                    continue
                result = parse_device_state(block.get("State"))
                self.device_states[device] = result
                if isinstance(result, KnownDeviceState):
                    current = self.agent_states.get(device, AgentState.OFFLINE)
                    new_state = agent_state_from_device_state(result.state, current)
                    self.agent_states[device] = new_state
                    logger.debug("agent state: %s → %s", device, new_state)
                    if new_state != current:
                        self._publish("agent_state_changed", {
                            "device": device,
                            "state": new_state,
                            "previous": current,
                        })
