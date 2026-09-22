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

import cognee
import requests
from strands import Agent, tool
from strands.memory import MemoryManager

from cognee_memory import DATASET_NAME, CogneeMemoryStore, connect_cognee
from sample_resources import categorize, get_domain
from test_brightdata import fetch_url, load_credentials
from test_cognee import FETCHED_TEXT_CHAR_LIMIT, html_to_text

SYSTEM_PROMPT = (
    "You are Flavia's personal learning brain: an assistant over her saved "
    "learning resources (articles, papers, LinkedIn posts, GitHub repos, talks). "
    "Answer concisely. When recalling saved material, include the original URL "
    "whenever it is available in memory."
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

    if auth_failed:
        return "Could not fetch: Bright Data authentication failed."
    if fields["fetch_status"] != "success":
        return f"Could not fetch {url}: {fields.get('fetch_error') or fields['fetch_status']}"

    domain = get_domain(url)
    source_type = categorize(domain)
    body = html_to_text(fields["fetched_text"])
    if len(body) > FETCHED_TEXT_CHAR_LIMIT:
        body = body[:FETCHED_TEXT_CHAR_LIMIT] + "..."

    memory_text = "\n".join([
        f"URL: {url}",
        f"Saved: {datetime.datetime.now().isoformat(timespec='seconds')}",
        f"Domain: {domain}",
        f"Source type: {source_type}",
        "Note before: (none)",
        "Note after: (none)",
        "Content:",
        body,
    ])

    await cognee.remember(memory_text, dataset_name=DATASET_NAME)
    return f"Saved and remembered {url} ({source_type}, domain: {domain})."


def build_agent():
    # Default Bedrock model (Anthropic via cross-region profile) is blocked on this
    # AWS account pending the "Anthropic use case details" form -- confirmed by
    # test_strands.py failing the same way, unmodified. Falling back to Nova Lite,
    # which this account can already call, to keep the hackathon demo working.
    memory_manager = MemoryManager(stores=[CogneeMemoryStore()])
    return Agent(
        model="us.amazon.nova-lite-v1:0",
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
