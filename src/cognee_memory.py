"""Cognee Cloud memory store for the Strands agent (hackathon-minimal).

Connects via cognee.serve() -- same pattern already proven in test_cognee.py
-- and exposes the existing `learning_brain_test` Cloud dataset as a Strands
MemoryManager MemoryStore. Read-only: ingestion of new URLs happens via the
dedicated fetch_and_remember tool in agent.py, which calls cognee.remember()
directly, so this store never writes to or deletes the dataset.
"""

import os
import re

import cognee
from cognee.api.v1.serve import is_remote_mode
from dotenv import load_dotenv
from strands.memory import MemoryEntry

DATASET_NAME = "learning_brain_test"
MAX_SEARCH_RESULTS = 5

URL_RE = re.compile(r"https?://[^\s\"'<>]+")


def extract_urls(text):
    if not text:
        return []
    urls = []
    for match in URL_RE.findall(str(text)):
        cleaned = match.rstrip(").,…")
        if cleaned not in urls:
            urls.append(cleaned)
    return urls


async def connect_cognee():
    """Connect this process to Cognee Cloud. Call once at agent startup."""
    load_dotenv()
    api_key = os.getenv("COGNEE_API_KEY")
    base_url = os.getenv("COGNEE_BASE_URL")
    if not api_key or not base_url:
        raise SystemExit("COGNEE_API_KEY and COGNEE_BASE_URL must both be set in .env")

    client = await cognee.serve(url=base_url, api_key=api_key)
    assert is_remote_mode() is True, "cognee.serve() returned but is_remote_mode() is False"
    return client


class CogneeMemoryStore:
    """Read-only Strands MemoryStore backed by the Cognee Cloud dataset."""

    name = "cognee_learning_brain"
    description = (
        "Flavia's saved learning resources (articles, papers, LinkedIn posts, "
        "GitHub repos, talks) stored in Cognee Cloud."
    )
    max_search_results = MAX_SEARCH_RESULTS
    writable = False
    extraction = None

    async def search(self, query, options=None):
        top_k = (options or {}).get("max_search_results") or self.max_search_results
        results = await cognee.recall(
            query,
            datasets=[DATASET_NAME],
            top_k=top_k,
            include_references=True,
        )
        entries = []
        for item in results:
            text = item.get("text")
            if not text:
                continue
            urls = extract_urls(text)
            entries.append(MemoryEntry(content=text, metadata={"urls": urls} if urls else None))
        return entries
