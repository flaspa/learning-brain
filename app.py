"""Minimal FastAPI UI for the Learning Brain demo.

Reuses the existing agent (src/agent.py) and Cognee Cloud connection
(src/cognee_memory.py) as-is -- no backend logic duplicated or changed.
"""

import json
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

DASHBOARD_INDEX_PATH = Path(__file__).parent / "output" / "dashboard_index.json"


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
TITLE_RE = re.compile(r"Title:\s*([^\n]+)")
URL_RE = re.compile(r"URL:\s*(\S+)")
RESOLVED_URL_RE = re.compile(r"Resolved URL:\s*(\S+)")
AUTHOR_RE = re.compile(r"Author:\s*([^\n]+)")
DOMAIN_RE = re.compile(r"Domain:\s*([^\n]+)")
SUMMARY_RE = re.compile(r"Summary:\s*([^\n]+)")
CONTENT_RE = re.compile(r"Content:\s*(.*)", re.DOTALL)


def _clean_field(value):
    """(unknown)/(none) placeholders embedded by the categorizer mean 'not
    set' -- normalize those to None instead of displaying them."""
    if not value:
        return None
    value = value.strip()
    if not value or value.lower() in ("(unknown)", "(none)"):
        return None
    return value


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


def build_matched_answer(cards):
    """Deterministic, no LLM call: a concise natural-language summary of the
    strongest retrieved match, built only from already-stored/retrieved
    fields. Never a raw URL dump -- the URL itself is shown via the rich
    preview card, not the prose."""
    best = cards[0]
    title = best.get("title") or "this resource"
    lead = f'"{title}"'
    if best.get("author"):
        lead += f" by {best['author']}"
    if best.get("domain"):
        lead += f" on {best['domain']}"
    lead += "."

    lines = ["I found the article you were thinking of.", "", lead]
    if best.get("description"):
        lines.append(best["description"])
    return "\n".join(lines)


def load_merged_resources():
    """Same enrichment /api/resources applies: dashboard_index.json (owned by
    the indexing job, read-only here) overlaid with manual_resources.json's
    preview fields."""
    resources = []
    if DASHBOARD_INDEX_PATH.exists():
        with DASHBOARD_INDEX_PATH.open("r", encoding="utf-8") as f:
            resources = json.load(f)
    manual_by_url = {r["url"]: r for r in load_manual_resources()}
    for r in resources:
        manual = manual_by_url.get(r["url"], {})
        r["preview_image"] = manual.get("preview_image")
        r["preview_title"] = manual.get("preview_title")
        r["preview_description"] = manual.get("preview_description")
        r["preview_site_name"] = manual.get("preview_site_name")
        r["resolved_url"] = manual.get("resolved_url")
    return resources


def build_resource_lookup():
    """url/resolved_url -> merged resource record, for enriching Ask's
    retrieved chunks with the same preview data the dashboard already has."""
    lookup = {}
    for r in load_merged_resources():
        lookup[r["url"]] = r
        if r.get("resolved_url"):
            lookup.setdefault(r["resolved_url"], r)
    for r in load_manual_resources():
        lookup.setdefault(r["url"], r)
        if r.get("resolved_url"):
            lookup.setdefault(r["resolved_url"], r)
    return lookup


def extract_card(text, resource_lookup):
    """Build a rich preview card from a chunk's embedded fields, enriched
    with stored preview metadata when the resource is already indexed. Never
    invents a URL -- returns None if one isn't present in the chunk."""
    if not text:
        return None
    url_match = URL_RE.search(text)
    if not url_match:
        return None
    url = url_match.group(1)
    resolved_match = RESOLVED_URL_RE.search(text)
    resolved_url = _clean_field(resolved_match.group(1)) if resolved_match else None

    resource = resource_lookup.get(url) or (resolved_url and resource_lookup.get(resolved_url)) or {}

    title_match = TITLE_RE.search(text)
    title = resource.get("title") or _clean_field(title_match.group(1) if title_match else None) or url

    author_match = AUTHOR_RE.search(text)
    author = resource.get("author") or _clean_field(author_match.group(1) if author_match else None)

    domain_match = DOMAIN_RE.search(text)
    domain = (
        resource.get("preview_site_name") or resource.get("domain")
        or _clean_field(domain_match.group(1) if domain_match else None)
    )

    summary_match = SUMMARY_RE.search(text)
    content_match = CONTENT_RE.search(text)
    content_excerpt = None
    if content_match:
        content_excerpt = re.sub(r"\s+", " ", content_match.group(1)).strip()[:280]
    description = (
        resource.get("short_summary") or resource.get("preview_description")
        or _clean_field(summary_match.group(1) if summary_match else None)
        or content_excerpt or None
    )

    categories, _tags = extract_categories_tags(text)
    return {
        "title": title,
        "url": resource.get("url") or url,
        "author": author,
        "domain": domain,
        "description": description,
        "category": categories[0] if categories else None,
        "preview_image": resource.get("preview_image"),
        "preview_title": resource.get("preview_title"),
    }


@app.post("/ask")
async def ask(req: AskRequest):
    result = await state["agent"].invoke_async(req.question)
    answer = THINKING_TAG_RE.sub("", str(result)).strip()
    if not answer:
        answer = "The agent didn't produce a direct answer -- please try rephrasing or asking again."

    categories, tags, used_to_answer = [], [], []
    try:
        # CHUNKS returns full untruncated chunk text (unlike a completion's
        # truncated evidence excerpts), so the Categories/Tags lines already
        # embedded by the existing categorizer are reliably present.
        recall_results = await cognee.recall(
            req.question, query_type=cognee.SearchType.CHUNKS, datasets=[DATASET_NAME], top_k=5
        )
        resource_lookup = build_resource_lookup()
        seen_urls = set()
        for item in recall_results:
            text = item.get("text")
            c, t = extract_categories_tags(text)
            categories.extend(x for x in c if x not in categories)
            tags.extend(x for x in t if x not in tags)

            card = extract_card(text, resource_lookup)
            if card and card["url"] not in seen_urls and len(used_to_answer) < 3:
                seen_urls.add(card["url"])
                used_to_answer.append(card)
    except Exception:
        pass

    # Retrieval (used_to_answer) and the agent's free-form generation come
    # from two separate calls and can disagree -- e.g. the model claims
    # nothing was found while a plausible match was actually retrieved, or it
    # answers correctly but dumps raw URLs into the prose. Rather than trying
    # to patch the model's phrasing, whenever retrieval found a match, the
    # displayed answer is always built deterministically from that retrieved
    # evidence -- grounded by construction, never a raw URL list. The model's
    # own answer is only shown when retrieval truly found nothing.
    if used_to_answer:
        answer = build_matched_answer(used_to_answer)

    return {"answer": answer, "categories": categories, "tags": tags, "used_to_answer": used_to_answer}


@app.post("/remember")
async def remember(req: RememberRequest):
    try:
        message = str(await fetch_and_remember(url=req.url))
        status = "success" if message.startswith("Saved and remembered") else "error"
        record = {}
        if status == "success":
            for r in load_manual_resources():
                if r["url"] == req.url:
                    record = r
                    break
        return {
            "status": status, "message": message,
            "categories": record.get("categories") or [],
            "tags": record.get("tags") or [],
            "author": record.get("author") or "",
            "summary": record.get("short_summary") or "",
            "preview_image": record.get("preview_image"),
            "preview_title": record.get("preview_title"),
            "preview_description": record.get("preview_description"),
            "preview_site_name": record.get("preview_site_name"),
            "resolved_url": record.get("resolved_url"),
        }
    except Exception as exc:
        return {"status": "error", "message": f"{type(exc).__name__}: {exc}"}


@app.get("/api/resources")
async def api_resources():
    return load_merged_resources()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
