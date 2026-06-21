import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from api.ami import AmiClient
from api.settings import Settings

settings = Settings()
ami = AmiClient(
    host=settings.ami_host,
    port=settings.ami_port,
    username=settings.ami_user,
    secret=settings.ami_secret,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await ami.connect()
    yield


app = FastAPI(title="asterisk-sandbox", lifespan=lifespan)

_STATIC = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=_STATIC), name="static")


@app.get("/")
def dashboard():
    return FileResponse(_STATIC / "index.html")


def _json(data) -> Response:
    return Response(
        content=json.dumps(jsonable_encoder(data)) + "\n",
        media_type="application/json",
    )


@app.get("/health")
def health():
    return Response(content='{"status": "ok"}\n', media_type="application/json")


@app.get("/calls")
def list_calls():
    return _json({
        "agent_states": ami.agent_states,
        "device_states": ami.device_states,
        "calls": [call.snapshot() for call in ami.tracker.calls.values()],
    })


class OriginateRequest(BaseModel):
    agent: str        # endpoint to ring, e.g. "6001"
    destination: str  # exten dialed once the agent answers, e.g. "6002"


@app.post("/originate")
async def originate(req: OriginateRequest):
    if req.agent not in ami.endpoint_numbers():
        raise HTTPException(status_code=404, detail=f"unknown endpoint: {req.agent}")
    channel_id = uuid4().hex
    await ami.originate(
        channel=f"PJSIP/{req.agent}",
        exten=req.destination,
        context=settings.originate_context,
        channel_id=channel_id,
        # name = who we're calling (shown on the agent's phone); number = the
        # agent, so call tracking identifies the originating leg correctly.
        caller_id=f'"{req.destination}" <{req.agent}>',
    )
    return _json({"channel_id": channel_id, "status": "originating"})


@app.get("/events")
async def event_stream():
    q = ami.subscribe()

    async def generate():
        snapshot = json.dumps(jsonable_encoder({
            "agent_states": ami.agent_states,
            "calls": [call.snapshot() for call in ami.tracker.calls.values()],
        }))
        yield f"event: snapshot\ndata: {snapshot}\n\n"
        try:
            while True:
                try:
                    chunk = await asyncio.wait_for(q.get(), timeout=30)
                    yield chunk
                except TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            ami.unsubscribe(q)

    return StreamingResponse(generate(), media_type="text/event-stream")
