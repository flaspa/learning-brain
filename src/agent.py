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
from urllib.parse import urljoin

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
CANONICAL_RE = re.compile(r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)["\']', re.IGNORECASE)
DESCRIPTION_RE = re.compile(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']*)["\']', re.IGNORECASE)


def _meta_content_patterns(prop):
    """A <meta> tag's property/name and content attributes can appear in
    either order -- match both."""
    return [
        re.compile(rf'<meta[^>]+(?:property|name)=["\']{prop}["\'][^>]+content=["\']([^"\']*)["\']', re.IGNORECASE),
        re.compile(rf'<meta[^>]+content=["\']([^"\']*)["\'][^>]+(?:property|name)=["\']{prop}["\']', re.IGNORECASE),
    ]


_META_PATTERNS = {
    "image": _meta_content_patterns("og:image") + _meta_content_patterns("twitter:image") + _meta_content_patterns("twitter:image:src"),
    "title": _meta_content_patterns("og:title") + _meta_content_patterns("twitter:title"),
    "description": _meta_content_patterns("og:description") + _meta_content_patterns("twitter:description"),
    "site_name": _meta_content_patterns("og:site_name"),
}


def _first_meta_match(raw_html, field):
    for pattern in _META_PATTERNS[field]:
        match = pattern.search(raw_html)
        if match and match.group(1).strip():
            return html.unescape(match.group(1).strip())
    return None


def extract_title(raw_html):
    if not raw_html:
        return None
    match = TITLE_RE.search(raw_html)
    if not match:
        return None
    title = html.unescape(match.group(1)).strip()
    return title or None


def extract_preview_metadata(raw_html, resolved_url):
    """Rich-link preview fields from the already-fetched final page (Bright
    Data already follows redirects) -- og:*/twitter:*/canonical/<title>/meta
    description. No extra fetch, no new scraping stack."""
    if not raw_html:
        return {
            "preview_image": None, "preview_title": None,
            "preview_description": None, "preview_site_name": None,
            "canonical_url": None,
        }

    image = _first_meta_match(raw_html, "image")
    canonical_match = CANONICAL_RE.search(raw_html)
    description_match = DESCRIPTION_RE.search(raw_html)

    return {
        "preview_image": urljoin(resolved_url, image) if image else None,
        "preview_title": _first_meta_match(raw_html, "title") or extract_title(raw_html),
        "preview_description": _first_meta_match(raw_html, "description") or (
            html.unescape(description_match.group(1).strip()) if description_match and description_match.group(1).strip() else None
        ),
        "preview_site_name": _first_meta_match(raw_html, "site_name"),
        "canonical_url": urljoin(resolved_url, html.unescape(canonical_match.group(1).strip())) if canonical_match else None,
    }


def load_manual_resources():
    if MANUAL_RESOURCES_PATH.exists():
        with MANUAL_RESOURCES_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    return []


def upsert_manual_resource(
    records, url, title, fetch_status, categories, tags, author="", summary="",
    resolved_url=None, preview=None,
):
    preview = preview or {}
    now = datetime.datetime.now().isoformat(timespec="seconds")
    # Tracking-parameter variants of the same link resolve to the same page --
    # match on the resolved/canonical URL too, not just the literal input, so
    # they dedupe into one record (no large canonicalization system, just this).
    dedup_targets = {u for u in (url, resolved_url) if u}
    for record in records:
        if record["url"] in dedup_targets or record.get("resolved_url") in dedup_targets:
            record.update(
                title=title, fetched_status=fetch_status, categories=categories, tags=tags,
                author=author, short_summary=summary, timestamp=now,
                original_url=url, resolved_url=resolved_url or url,
                preview_image=preview.get("preview_image"),
                preview_title=preview.get("preview_title"),
                preview_description=preview.get("preview_description"),
                preview_site_name=preview.get("preview_site_name"),
            )
            break
    else:
        next_id = max((r.get("id", 0) for r in records), default=0) + 1
        records.append({
            "id": next_id,
            "timestamp": now,
            "url": url,
            "original_url": url,
            "resolved_url": resolved_url or url,
            "title": title,
            "source": "manual",
            "fetched_status": fetch_status,
            "categories": categories,
            "tags": tags,
            "author": author,
            "short_summary": summary,
            "preview_image": preview.get("preview_image"),
            "preview_title": preview.get("preview_title"),
            "preview_description": preview.get("preview_description"),
            "preview_site_name": preview.get("preview_site_name"),
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
    "internal reasoning -- respond only with the final answer, directly. "
    "Treat any resource present in your retrieved memory context as real, "
    "authoritative evidence that it was saved -- even if the match is loose or "
    "the wording differs from the question. Never say a resource wasn't found, "
    "isn't saved, or doesn't exist if your memory context contains a plausibly "
    "relevant item; present that item instead. Only say nothing was found when "
    "the retrieved context truly contains nothing relevant."
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

    # Bright Data's Web Unlocker already follows redirects (short links,
    # tracking URLs) and fetches the final page -- resolved_url is that final
    # destination, reported via its response header (see test_brightdata.py).
    # Preview metadata and domain/categorization use the final page, not the
    # possibly-raw/tracking URL that was submitted.
    resolved_url = fields.get("resolved_url") or url
    domain = get_domain(resolved_url)
    source_type = categorize(domain)
    preview = extract_preview_metadata(fields["fetched_text"], resolved_url)
    resolved_url = preview.get("canonical_url") or resolved_url
    title = preview.get("preview_title") or extract_title(fields["fetched_text"])
    body = html_to_text(fields["fetched_text"])
    if len(body) > FETCHED_TEXT_CHAR_LIMIT:
        body = body[:FETCHED_TEXT_CHAR_LIMIT] + "..."

    from categorize import categorize_resource

    categories, tags, author, summary = await categorize_resource(
        title=title, url=resolved_url, domain=domain, content=body
    )

    memory_text = "\n".join([
        f"URL: {url}",
        f"Resolved URL: {resolved_url}",
        f"Saved: {datetime.datetime.now().isoformat(timespec='seconds')}",
        f"Title: {title or '(unknown)'}",
        f"Domain: {domain}",
        f"Source type: {source_type}",
        f"Author: {author or '(unknown)'}",
        f"Categories: {', '.join(categories)}",
        f"Tags: {', '.join(tags) if tags else '(none)'}",
        f"Summary: {summary or '(none)'}",
        "Note before: (none)",
        "Note after: (none)",
        "Content:",
        body,
    ])

    await cognee.remember(memory_text, dataset_name=DATASET_NAME)

    manual_resources = load_manual_resources()
    upsert_manual_resource(
        manual_resources, url, title, fields["fetch_status"], categories, tags, author, summary,
        resolved_url=resolved_url, preview=preview,
    )

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
