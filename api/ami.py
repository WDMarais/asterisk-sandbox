import asyncio
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

    async def connect(self) -> None:
        self._reader, self._writer = await asyncio.open_connection(self.host, self.port)
        greeting = await self._reader.readline()
        logger.info("AMI: %s", greeting.decode().strip())
        await self._login()
        await self._request_device_state_list()
        asyncio.create_task(self._event_loop())

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
        while True:
            try:
                block = await self._read_block()
            except Exception:
                logger.exception("AMI connection lost")
                break
            if block.get("Event") == "DeviceStateChange":
                device = block.get("Device", "")
                if not device or not device.startswith(("PJSIP/", "SIP/")):
                    continue
                result = parse_device_state(block.get("State"))
                self.device_states[device] = result
                if isinstance(result, KnownDeviceState):
                    current = self.agent_states.get(device, AgentState.OFFLINE)
                    self.agent_states[device] = agent_state_from_device_state(
                        result.state, current
                    )
                    logger.debug("agent state: %s → %s", device, self.agent_states[device])
