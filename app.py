"""Minimal FastAPI UI for the Learning Brain demo.

Reuses the existing agent (src/agent.py) and Cognee Cloud connection
(src/cognee_memory.py) as-is -- no backend logic duplicated or changed.
"""

import re
import sys
from pathlib import Path

SRC_DIR = Path(__file__).parent / "src"
sys.path.insert(0, str(SRC_DIR))

from contextlib import asynccontextmanager

import cognee
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agent import build_agent, fetch_and_remember
from cognee_memory import connect_cognee

state = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_cognee()
    state["agent"] = build_agent()
    yield
    await cognee.disconnect()


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


class AskRequest(BaseModel):
    question: str


class RememberRequest(BaseModel):
    url: str


@app.get("/")
async def index():
    return FileResponse(Path(__file__).parent / "templates" / "index.html")


THINKING_TAG_RE = re.compile(r"<thinking>.*?</thinking>", re.DOTALL)


@app.post("/ask")
async def ask(req: AskRequest):
    result = await state["agent"].invoke_async(req.question)
    answer = THINKING_TAG_RE.sub("", str(result)).strip()
    if not answer:
        answer = "The agent didn't produce a direct answer -- please try rephrasing or asking again."
    return {"answer": answer}


@app.post("/remember")
async def remember(req: RememberRequest):
    try:
        message = str(await fetch_and_remember(url=req.url))
        status = "success" if message.startswith("Saved and remembered") else "error"
        return {"status": status, "message": message}
    except Exception as exc:
        return {"status": "error", "message": f"{type(exc).__name__}: {exc}"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
