from fastapi import FastAPI

app = FastAPI(title="asterisk-sandbox")


@app.get("/health")
def health():
    return {"status": "ok"}


# Placeholder — will talk to Asterisk AMI
@app.get("/calls")
def list_calls():
    return {"calls": []}
