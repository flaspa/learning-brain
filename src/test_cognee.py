"""Cognee Cloud ingestion and recall test for the learning_brain_test dataset.

Connects the SDK to the hosted Cognee Cloud workspace via cognee.serve(), so
remember()/recall() route over HTTPS to that instance instead of running
locally. Reads output/brightdata_test.json only and never modifies it.

Env loading: VS Code's terminal env-file injection is disabled in this
project, so COGNEE_API_KEY and COGNEE_BASE_URL are not implicitly present in
the process environment. load_dotenv() is called explicitly and both are
read via os.getenv() before connecting -- cognee.serve()'s own env-var
auto-detection only looks for COGNEE_SERVICE_URL, not COGNEE_BASE_URL, so the
value is passed to serve(url=...) directly rather than relying on that.

The cloud client returns plain dicts (result["text"], result.get("source")),
not the attribute-style objects (entry.text) that local recall() returns.
"""

import asyncio
import json
import os
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from uuid import UUID

import cognee
from cognee.api.v1.serve import is_remote_mode
from dotenv import load_dotenv

from sample_resources import categorize, get_domain

# Cloud recall answers can contain characters (curly quotes, non-breaking
# hyphens) outside Windows' default console codepage; without this, printing
# them crashes the whole run partway through.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

INPUT_PATH = Path("output/brightdata_test.json")
DATASET_NAME = "learning_brain_test"
FETCHED_TEXT_CHAR_LIMIT = 6000
ANSWER_PREVIEW_CHARS = 500

LIST_DATA_POLL_ATTEMPTS = 12
LIST_DATA_POLL_SECONDS = 10
RECALL_RETRY_ATTEMPTS = 6
RECALL_RETRY_SECONDS = 10

RECALL_TESTS = [
    ("vague memory", "I remember saving something about machine learning or Bayesian ideas. What was it?"),
    ("source retrieval", "Which LinkedIn resource did I save?"),
    ("cross-resource", "What themes connect the resources I saved?"),
]

URL_RE = re.compile(r"https?://[^\s\"'<>]+")


class _TextExtractor(HTMLParser):
    """Minimal, dependency-free HTML-to-text extractor (drops script/style)."""

    def __init__(self):
        super().__init__()
        self._skip = False
        self.chunks = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip = True

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = False

    def handle_data(self, data):
        if not self._skip:
            text = data.strip()
            if text:
                self.chunks.append(text)


def html_to_text(html):
    if not html:
        return ""
    parser = _TextExtractor()
    parser.feed(html)
    return " ".join(parser.chunks)


def load_success_records(path):
    with path.open("r", encoding="utf-8") as f:
        records = json.load(f)
    return [r for r in records if r.get("fetch_status") == "success"]


def build_memory_text(record):
    domain = get_domain(record["url"])
    source_type = categorize(domain)

    body = html_to_text(record.get("fetched_text"))
    if len(body) > FETCHED_TEXT_CHAR_LIMIT:
        body = body[:FETCHED_TEXT_CHAR_LIMIT] + "..."

    return "\n".join([
        f"URL: {record['url']}",
        f"Saved: {record['timestamp']}",
        f"Domain: {domain}",
        f"Source type: {source_type}",
        f"Note before: {record.get('note_before') or '(none)'}",
        f"Note after: {record.get('note_after') or '(none)'}",
        "Content:",
        body,
    ])


def extract_urls(text):
    if not text:
        return []
    urls = []
    for match in URL_RE.findall(str(text)):
        if match not in urls:
            urls.append(match)
    return urls


def preview(text, limit=ANSWER_PREVIEW_CHARS):
    text = (text or "").strip()
    if len(text) > limit:
        return text[:limit] + "..."
    return text


async def connect():
    load_dotenv()
    api_key = os.getenv("COGNEE_API_KEY")
    base_url = os.getenv("COGNEE_BASE_URL")
    if not api_key or not base_url:
        raise SystemExit("COGNEE_API_KEY and COGNEE_BASE_URL must both be set in .env")

    client = await cognee.serve(url=base_url, api_key=api_key)
    assert is_remote_mode() is True, "cognee.serve() returned but is_remote_mode() is False"
    print(f"Connected to Cognee Cloud (remote mode): {client.service_url}")
    return client


async def wait_for_remote_items(dataset_id, expected_count):
    items = []
    for attempt in range(LIST_DATA_POLL_ATTEMPTS):
        items = await cognee.datasets.list_data(UUID(dataset_id))
        print(f"  poll {attempt + 1}/{LIST_DATA_POLL_ATTEMPTS}: {len(items)}/{expected_count} items visible server-side")
        if len(items) >= expected_count:
            break
        await asyncio.sleep(LIST_DATA_POLL_SECONDS)
    return items


async def ingest(records):
    memories = [build_memory_text(r) for r in records]
    print(f"Ingesting {len(memories)} memories into Cloud dataset '{DATASET_NAME}' ...")
    result = await cognee.remember(memories, dataset_name=DATASET_NAME)
    print(f"Ingest response: {result}")

    items = await wait_for_remote_items(result["dataset_id"], len(memories))
    return result, items


async def recall_with_retry(query):
    """The server can 409 briefly while the graph for a fresh dataset is still building."""
    last_error = None
    for attempt in range(RECALL_RETRY_ATTEMPTS):
        try:
            return await cognee.recall(query, datasets=[DATASET_NAME], top_k=5)
        except RuntimeError as exc:
            last_error = exc
            if "409" not in str(exc):
                raise
            print(f"  recall not ready yet (attempt {attempt + 1}/{RECALL_RETRY_ATTEMPTS}), retrying...")
            await asyncio.sleep(RECALL_RETRY_SECONDS)
    raise last_error


async def run_recall_tests():
    summaries = []
    for label, query in RECALL_TESTS:
        print(f"\n=== {label} ===")
        print(f"Query: {query}")
        try:
            results = await recall_with_retry(query)
        except Exception as exc:
            print(f"Recall failed: {type(exc).__name__}: {exc}")
            summaries.append((label, None, []))
            continue

        if not results:
            print("No results.")
            summaries.append((label, None, []))
            continue

        top = results[0]
        text = top.get("text")
        urls = extract_urls(text)
        print(f"[{top.get('source', '?')}] {preview(text)}")
        if urls:
            print(f"  Source URLs: {', '.join(urls)}")
        summaries.append((label, preview(text, 200), urls))
    return summaries


async def main():
    records = load_success_records(INPUT_PATH)
    print(f"Loaded {len(records)} successfully fetched record(s) from {INPUT_PATH}")

    if not records:
        print("No successful records to ingest.")
        return

    await connect()
    try:
        result, items = await ingest(records)
        all_completed = len(items) >= len(records)
        print(f"\nDataset ID: {result['dataset_id']}")
        print(f"Resources ingested: {len(records)}")
        print(f"All {len(records)} completed server-side: {all_completed}")

        summaries = await run_recall_tests()

        print("\n=== Summary ===")
        for label, answer, urls in summaries:
            print(f"- {label}: {answer or '(no result)'}")
            if urls:
                print(f"  URLs: {', '.join(urls)}")
    finally:
        await cognee.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
