import asyncio
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class AmiClient:
    host: str
    port: int
    username: str
    secret: str
    device_states: dict[str, str] = field(default_factory=dict)
    _reader: asyncio.StreamReader | None = field(default=None, repr=False)
    _writer: asyncio.StreamWriter | None = field(default=None, repr=False)

    async def connect(self) -> None:
        self._reader, self._writer = await asyncio.open_connection(self.host, self.port)
        greeting = await self._reader.readline()
        logger.info("AMI: %s", greeting.decode().strip())
        await self._login()
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

    async def _event_loop(self) -> None:
        while True:
            try:
                block = await self._read_block()
            except Exception:
                logger.exception("AMI connection lost")
                break
            if block.get("Event") == "DeviceStateChange":
                device = block.get("Device", "")
                state = block.get("State", "")
                if device:
                    self.device_states[device] = state
                    logger.debug("device state: %s → %s", device, state)
