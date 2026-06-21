import asyncio
import json
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.responses import Response, StreamingResponse

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
