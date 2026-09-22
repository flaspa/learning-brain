"""Build output/dashboard_index.json: the enriched resource index that powers
the dashboard UI (Topics / Sources / People views).

Covers ALL successfully-ingested resources (output/whatsapp_ingest_progress.json
status=="success") plus all manual resources (output/manual_resources.json).
Never re-fetches Bright Data. Resumable: an existing dashboard_index.json is
loaded first and already-enriched records are skipped, so interrupting and
re-running only processes what's left.

Fast path (no LLM call): pull back the already-stored Cognee memory document
via a content-relevant CHUNKS search and parse its Title/Categories/Tags/
Author/Summary lines directly -- most records ingested after categorization
was added already have these embedded.

Fallback (one LLM call, same Nova Lite model already wired up): only for
records whose stored document has no Categories: line at all (pre-dates
categorization), reusing categorize_resource() to backfill everything at once.

If no stored content can be found, category defaults to ["Other"] and
author/summary are left empty -- never invented.

CLI:
    python src/build_dashboard_index.py            # process everything not yet indexed
    python src/build_dashboard_index.py --limit 100 # bound this run (resumable)
"""

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

import cognee

from categorize import categorize_resource
from cognee_memory import DATASET_NAME, connect_cognee
from sample_resources import categorize as domain_category, get_domain

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

WHATSAPP_LINKS_PATH = Path("output/whatsapp_links.json")
WHATSAPP_PROGRESS_PATH = Path("output/whatsapp_ingest_progress.json")
MANUAL_RESOURCES_PATH = Path("output/manual_resources.json")
DASHBOARD_INDEX_PATH = Path("output/dashboard_index.json")

TITLE_RE = re.compile(r"Title:\s*([^\n]+)")
CATEGORIES_RE = re.compile(r"Categories:\s*([^\n]+)")
TAGS_RE = re.compile(r"Tags:\s*([^\n]+)")
AUTHOR_RE = re.compile(r"Author:\s*([^\n]+)")
SUMMARY_RE = re.compile(r"Summary:\s*([^\n]+)")
CONTENT_RE = re.compile(r"Content:\s*(.*)", re.DOTALL)
CONTENT_EXCERPT_CHARS = 1500


def load_json(path, default):
    if path.exists():
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    return default


def save_index(index_by_id):
    DASHBOARD_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    with DASHBOARD_INDEX_PATH.open("w", encoding="utf-8") as f:
        json.dump(list(index_by_id.values()), f, ensure_ascii=False, indent=2)


def build_query(url, domain, title=None, note=None):
    """A bare URL embeds poorly for semantic search; build a content-relevant
    keyword query instead (title/note preferred, else humanized URL path)."""
    if title and title != domain:
        return title
    if note:
        return note
    path = urlsplit(url).path
    words = re.sub(r"[-_/]+", " ", path)
    words = re.sub(r"\.\w+$", "", words).strip()
    return f"{domain} {words}".strip()


def _clean_list(raw):
    if not raw:
        return []
    items = [x.strip() for x in raw.split(",")]
    return [x for x in items if x and x.lower() != "(none)"]


def parse_stored_fields(text):
    """Parse Title/Categories/Tags/Author/Summary/Content already embedded in
    a stored memory document by the existing categorizer/ingestion code."""
    title_m = TITLE_RE.search(text)
    author_m = AUTHOR_RE.search(text)
    summary_m = SUMMARY_RE.search(text)
    content_m = CONTENT_RE.search(text)
    return {
        "title": title_m.group(1).strip() if title_m else "",
        "categories": _clean_list(CATEGORIES_RE.search(text).group(1)) if CATEGORIES_RE.search(text) else [],
        "tags": _clean_list(TAGS_RE.search(text).group(1)) if TAGS_RE.search(text) else [],
        "author": (author_m.group(1).strip() if author_m and author_m.group(1).strip().lower() != "(unknown)" else ""),
        "summary": (summary_m.group(1).strip() if summary_m and summary_m.group(1).strip().lower() != "(none)" else ""),
        "content": (content_m.group(1) if content_m else "")[:CONTENT_EXCERPT_CHARS],
    }


async def fetch_stored_chunk(query, url):
    """Pull back the already-stored chunk text for a URL via CHUNKS search. No Bright Data fetch."""
    try:
        results = await cognee.recall(
            query, query_type=cognee.SearchType.CHUNKS, datasets=[DATASET_NAME], top_k=5
        )
    except Exception:
        return ""
    for item in results:
        text = item.get("text") or ""
        if url in text:
            return text
    return ""


def source_type_for(url):
    domain = get_domain(url)
    return domain, domain_category(domain)


async def enrich_one(url, domain, query, fallback_title, note=None):
    """Fast path: parse stored fields. Fallback: one LLM call if no
    categories were found in storage. Never re-fetches Bright Data."""
    chunk = await fetch_stored_chunk(query, url)
    if not chunk:
        return {"title": fallback_title, "categories": ["Other"], "tags": [], "author": "", "summary": ""}

    parsed = parse_stored_fields(chunk)
    if parsed["categories"]:
        return {
            "title": parsed["title"] or fallback_title,
            "categories": parsed["categories"],
            "tags": parsed["tags"],
            "author": parsed["author"],
            "summary": parsed["summary"],
        }

    # Legacy document with no embedded categorization -- one LLM call to backfill.
    categories, tags, author, summary = await categorize_resource(
        title=parsed["title"] or fallback_title, url=url, domain=domain,
        note=note, content=parsed["content"],
    )
    return {
        "title": parsed["title"] or fallback_title,
        "categories": categories,
        "tags": tags,
        "author": author,
        "summary": summary,
    }


async def process_whatsapp(index_by_id, limit):
    records = {str(r["id"]): r for r in load_json(WHATSAPP_LINKS_PATH, [])}
    progress = load_json(WHATSAPP_PROGRESS_PATH, {})
    success_ids = [rid for rid, v in progress.items() if v.get("status") == "success"]

    done = 0
    for record_id in success_ids:
        key = f"whatsapp:{record_id}"
        if key in index_by_id:
            continue
        if done >= limit:
            break
        record = records.get(record_id)
        if not record:
            continue

        url = record["url"]
        domain, source_type = source_type_for(url)
        note = record.get("note_before") or record.get("note_after")
        query = build_query(url, domain, note=note)
        result = await enrich_one(url, domain, query, fallback_title=note or domain, note=note)

        index_by_id[key] = {
            "id": key,
            "title": result["title"],
            "url": url,
            "domain": domain,
            "source_type": source_type,
            "author": result["author"],
            "timestamp": record.get("timestamp"),
            "categories": result["categories"],
            "tags": result["tags"],
            "short_summary": result["summary"],
        }
        save_index(index_by_id)
        done += 1
        if done % 10 == 0:
            print(f"  ... {done} whatsapp resources processed this run")
    print(f"  whatsapp: {done} newly processed, {len(success_ids) - done} already indexed or skipped")
    return done


async def process_manual(index_by_id, limit):
    manual = load_json(MANUAL_RESOURCES_PATH, [])

    done = 0
    for record in manual:
        key = f"manual:{record['id']}"
        if key in index_by_id:
            continue
        if done >= limit:
            break

        url = record["url"]
        domain, source_type = source_type_for(url)
        title = record.get("title") or domain
        categories = record.get("categories") or []
        tags = record.get("tags") or []
        author = record.get("author") or ""
        summary = record.get("short_summary") or ""

        if not categories:
            query = build_query(url, domain, title=title)
            result = await enrich_one(url, domain, query, fallback_title=title)
            categories, tags = result["categories"], result["tags"]
            author, summary = author or result["author"], summary or result["summary"]

        index_by_id[key] = {
            "id": key,
            "title": title,
            "url": url,
            "domain": domain,
            "source_type": source_type,
            "author": author,
            "timestamp": record.get("timestamp"),
            "categories": categories,
            "tags": tags,
            "short_summary": summary,
        }
        save_index(index_by_id)
        done += 1
    print(f"  manual: {done} newly processed")
    return done


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=10_000, help="max NEW resources to process this run (per source)")
    args = parser.parse_args()

    existing = load_json(DASHBOARD_INDEX_PATH, [])
    index_by_id = {r["id"]: r for r in existing}
    print(f"Starting from {len(index_by_id)} already-indexed resources.")

    await connect_cognee()
    try:
        await process_manual(index_by_id, args.limit)
        await process_whatsapp(index_by_id, args.limit)
    finally:
        await cognee.disconnect()

    resources = list(index_by_id.values())
    topics = {c for r in resources for c in r["categories"]}
    sources = {r["source_type"] for r in resources}
    author_counts = {}
    for r in resources:
        if r["author"]:
            author_counts[r["author"]] = author_counts.get(r["author"], 0) + 1
    recurring_people = sum(1 for c in author_counts.values() if c >= 2)
    with_summary = sum(1 for r in resources if r["short_summary"])
    with_author = sum(1 for r in resources if r["author"])

    print("\n=== Summary ===")
    print(f"Total indexed resources: {len(resources)}")
    print(f"Total topics: {len(topics)}")
    print(f"Total source groups: {len(sources)}")
    print(f"Recurring people (>=2 saved): {recurring_people}")
    print(f"Resources with summaries: {with_summary}")
    print(f"Resources with authors: {with_author}")
    print(f"Index file: {DASHBOARD_INDEX_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
