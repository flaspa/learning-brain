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

from agent import build_agent, fetch_and_remember, load_manual_resources
from cognee_memory import DATASET_NAME, connect_cognee

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
CATEGORIES_RE = re.compile(r"Categories:\s*([^\n]+)")
TAGS_RE = re.compile(r"Tags:\s*([^\n]+)")


def extract_categories_tags(text):
    """Pull 'Categories: a, b' / 'Tags: x, y' lines already embedded in memory
    documents by the existing categorizer. Never invents values."""
    categories, tags = [], []
    if not text:
        return categories, tags
    for match in CATEGORIES_RE.finditer(text):
        for item in match.group(1).split(","):
            item = item.strip()
            if item and item.lower() != "(none)" and item not in categories:
                categories.append(item)
    for match in TAGS_RE.finditer(text):
        for item in match.group(1).split(","):
            item = item.strip()
            if item and item.lower() != "(none)" and item not in tags:
                tags.append(item)
    return categories, tags


@app.post("/ask")
async def ask(req: AskRequest):
    result = await state["agent"].invoke_async(req.question)
    answer = THINKING_TAG_RE.sub("", str(result)).strip()
    if not answer:
        answer = "The agent didn't produce a direct answer -- please try rephrasing or asking again."

    categories, tags = [], []
    try:
        # CHUNKS returns full untruncated chunk text (unlike a completion's
        # truncated evidence excerpts), so the Categories/Tags lines already
        # embedded by the existing categorizer are reliably present.
        recall_results = await cognee.recall(
            req.question, query_type=cognee.SearchType.CHUNKS, datasets=[DATASET_NAME], top_k=3
        )
        for item in recall_results:
            c, t = extract_categories_tags(item.get("text"))
            categories.extend(x for x in c if x not in categories)
            tags.extend(x for x in t if x not in tags)
    except Exception:
        pass

    return {"answer": answer, "categories": categories, "tags": tags}


@app.post("/remember")
async def remember(req: RememberRequest):
    try:
        message = str(await fetch_and_remember(url=req.url))
        status = "success" if message.startswith("Saved and remembered") else "error"
        categories, tags = [], []
        if status == "success":
            for record in load_manual_resources():
                if record["url"] == req.url:
                    categories = record.get("categories") or []
                    tags = record.get("tags") or []
                    break
        return {"status": status, "message": message, "categories": categories, "tags": tags}
    except Exception as exc:
        return {"status": "error", "message": f"{type(exc).__name__}: {exc}"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
