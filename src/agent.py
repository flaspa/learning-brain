"""Learning Brain Strands agent: Cognee Cloud memory + Bright Data ingestion.

Hackathon-minimal: reuses the already-working Strands setup from
test_strands.py (default model resolution, no override), the Bright Data
fetch logic from test_brightdata.py, and the HTML-to-text helper from
test_cognee.py. No FastAPI, no UI, no deployment.

Usage:
    python src/agent.py            # runs the demo queries once
    python src/agent.py --chat     # interactive CLI
"""

import argparse
import asyncio
import datetime
import html
import json
import re
from pathlib import Path

import cognee
import requests
from strands import Agent, tool
from strands.memory import MemoryManager

from cognee_memory import DATASET_NAME, CogneeMemoryStore, connect_cognee
from sample_resources import categorize, get_domain
from test_brightdata import fetch_url, load_credentials
from test_cognee import FETCHED_TEXT_CHAR_LIMIT, html_to_text

MANUAL_RESOURCES_PATH = Path("output/manual_resources.json")
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


def extract_title(raw_html):
    if not raw_html:
        return None
    match = TITLE_RE.search(raw_html)
    if not match:
        return None
    title = html.unescape(match.group(1)).strip()
    return title or None


def load_manual_resources():
    if MANUAL_RESOURCES_PATH.exists():
        with MANUAL_RESOURCES_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    return []


def upsert_manual_resource(records, url, title, fetch_status, categories, tags):
    now = datetime.datetime.now().isoformat(timespec="seconds")
    for record in records:
        if record["url"] == url:
            record.update(title=title, fetched_status=fetch_status, categories=categories, tags=tags, timestamp=now)
            break
    else:
        next_id = max((r.get("id", 0) for r in records), default=0) + 1
        records.append({
            "id": next_id,
            "timestamp": now,
            "url": url,
            "title": title,
            "source": "manual",
            "fetched_status": fetch_status,
            "categories": categories,
            "tags": tags,
        })
    MANUAL_RESOURCES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with MANUAL_RESOURCES_PATH.open("w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    return records

# Default Bedrock model (Anthropic via cross-region profile) is blocked on this
# AWS account pending the "Anthropic use case details" form -- Nova Lite is
# already callable on this account. Shared with categorize.py.
MODEL_ID = "us.amazon.nova-lite-v1:0"

SYSTEM_PROMPT = (
    "You are Flavia's personal learning brain: an assistant over her saved "
    "learning resources (articles, papers, LinkedIn posts, GitHub repos, talks). "
    "Answer concisely. When recalling saved material, include the original URL "
    "whenever it is available in memory. Never output <thinking> tags or any "
    "internal reasoning -- respond only with the final answer, directly."
)

DEMO_QUERIES = [
    "What was that LinkedIn post I saved about computer vision?",
    "What machine learning material have I saved?",
    "Explicitly search your learning memory for anything about graph RAG or knowledge graphs, and tell me what you find.",
]


@tool
async def fetch_and_remember(url: str) -> str:
    """Fetch a public URL with Bright Data and store it in Cognee Cloud memory.

    Args:
        url: The public URL to fetch and remember.
    """
    api_key, zone = load_credentials()
    session = requests.Session()
    fields, auth_failed = fetch_url(session, api_key, zone, url)

    # Bright Data can be slow on some pages (e.g. LinkedIn); retry once, only
    # on a timeout, before giving up.
    if not auth_failed and fields["fetch_status"] != "success" and "timed out" in (fields.get("fetch_error") or "").lower():
        fields, auth_failed = fetch_url(session, api_key, zone, url)

    if auth_failed:
        return "Could not fetch: Bright Data authentication failed."
    if fields["fetch_status"] != "success":
        return f"Could not fetch {url}: {fields.get('fetch_error') or fields['fetch_status']}"

    domain = get_domain(url)
    source_type = categorize(domain)
    title = extract_title(fields["fetched_text"])
    body = html_to_text(fields["fetched_text"])
    if len(body) > FETCHED_TEXT_CHAR_LIMIT:
        body = body[:FETCHED_TEXT_CHAR_LIMIT] + "..."

    from categorize import categorize_resource

    categories, tags = await categorize_resource(title=title, url=url, domain=domain, content=body)

    memory_text = "\n".join([
        f"URL: {url}",
        f"Saved: {datetime.datetime.now().isoformat(timespec='seconds')}",
        f"Title: {title or '(unknown)'}",
        f"Domain: {domain}",
        f"Source type: {source_type}",
        f"Categories: {', '.join(categories)}",
        f"Tags: {', '.join(tags) if tags else '(none)'}",
        "Note before: (none)",
        "Note after: (none)",
        "Content:",
        body,
    ])

    await cognee.remember(memory_text, dataset_name=DATASET_NAME)

    manual_resources = load_manual_resources()
    upsert_manual_resource(manual_resources, url, title, fields["fetch_status"], categories, tags)

    return f"Saved and remembered {url} ({source_type}, domain: {domain}, categories: {', '.join(categories)})."


def build_agent():
    # Default Bedrock model (Anthropic via cross-region profile) is blocked on this
    # AWS account pending the "Anthropic use case details" form -- confirmed by
    # test_strands.py failing the same way, unmodified. Falling back to Nova Lite,
    # which this account can already call, to keep the hackathon demo working.
    memory_manager = MemoryManager(stores=[CogneeMemoryStore()])
    return Agent(
        model=MODEL_ID,
        system_prompt=SYSTEM_PROMPT,
        tools=[fetch_and_remember],
        memory_manager=memory_manager,
    )


async def run_demo(agent, fetch_test_url=None):
    for query in DEMO_QUERIES:
        print(f"\n>>> {query}")
        result = await agent.invoke_async(query)
        print(result)

    if fetch_test_url:
        print(f"\n>>> Fetch and remember: {fetch_test_url}")
        result = await agent.invoke_async(
            f"Fetch this URL and remember it in my learning brain: {fetch_test_url}"
        )
        print(result)


async def chat_loop(agent):
    print("Learning Brain agent -- type 'exit' to quit.")
    while True:
        try:
            user_input = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if user_input.lower() in ("exit", "quit"):
            break
        if not user_input:
            continue
        result = await agent.invoke_async(user_input)
        print(f"agent> {result}")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--chat", action="store_true", help="interactive CLI mode")
    parser.add_argument("--fetch-test-url", default=None, help="also test fetch_and_remember on this URL")
    args = parser.parse_args()

    await connect_cognee()
    agent = build_agent()

    try:
        if args.chat:
            await chat_loop(agent)
        else:
            await run_demo(agent, fetch_test_url=args.fetch_test_url)
    finally:
        await cognee.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
