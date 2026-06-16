import json
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.responses import Response

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


@app.get("/health")
def health():
    return Response(content='{"status": "ok"}\n', media_type="application/json")


@app.get("/calls")
def list_calls():
    data = {"agent_states": ami.agent_states, "device_states": ami.device_states}
    return Response(content=json.dumps(jsonable_encoder(data)) + "\n", media_type="application/json")
