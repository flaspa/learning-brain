"""Backfill categories/tags for already-ingested resources, without re-fetching
pages from Bright Data.

Classifies from URL/domain/note/title only (whatever is already on disk) and
adds a small companion memory document per resource into the existing Cognee
Cloud dataset (learning_brain_test), so categorized recall works without
duplicating or rewriting the original content. Never touches
output/whatsapp_links.json.

Resumable: output/category_backfill_progress.json tracks what's already done.

CLI:
    python src/backfill_categories.py                                  # first test: 10 whatsapp + 3 manual
    python src/backfill_categories.py --whatsapp-limit 1592 --manual-limit 1000  # backfill the remainder
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

import cognee

from categorize import categorize_resource
from cognee_memory import DATASET_NAME, connect_cognee
from sample_resources import get_domain

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

WHATSAPP_LINKS_PATH = Path("output/whatsapp_links.json")
WHATSAPP_PROGRESS_PATH = Path("output/whatsapp_ingest_progress.json")
MANUAL_RESOURCES_PATH = Path("output/manual_resources.json")
BACKFILL_PROGRESS_PATH = Path("output/category_backfill_progress.json")


def load_json(path, default):
    if path.exists():
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def build_backfill_doc(url, categories, tags, note):
    return "\n".join([
        f"URL: {url}",
        f"Categories: {', '.join(categories)}",
        f"Tags: {', '.join(tags) if tags else '(none)'}",
        f"({note})",
    ])


async def backfill_whatsapp(limit, backfill_progress):
    records = {str(r["id"]): r for r in load_json(WHATSAPP_LINKS_PATH, [])}
    ingest_progress = load_json(WHATSAPP_PROGRESS_PATH, {})
    success_ids = [rid for rid, v in ingest_progress.items() if v.get("status") == "success"]

    done = 0
    for record_id in success_ids:
        if done >= limit:
            break
        key = f"whatsapp:{record_id}"
        if backfill_progress.get(key):
            continue
        record = records.get(record_id)
        if not record:
            continue

        note = record.get("note_before") or record.get("note_after")
        domain = get_domain(record["url"])
        categories, tags, author, _summary = await categorize_resource(
            url=record["url"], domain=domain, note=note, content=""
        )

        doc = build_backfill_doc(
            record["url"], categories, tags,
            "Category/tag backfill for an already-ingested WhatsApp resource",
        )
        await cognee.remember(doc, dataset_name=DATASET_NAME)

        backfill_progress[key] = {"url": record["url"], "categories": categories, "tags": tags, "author": author}
        save_json(BACKFILL_PROGRESS_PATH, backfill_progress)
        print(f"  [whatsapp:{record_id}] {record['url']} -> {categories} {tags}")
        done += 1
    return done


async def backfill_manual(limit, backfill_progress):
    manual = load_json(MANUAL_RESOURCES_PATH, [])
    done = 0
    changed = False
    for record in manual:
        if done >= limit:
            break
        key = f"manual:{record['id']}"
        if backfill_progress.get(key):
            continue

        domain = get_domain(record["url"])
        categories, tags, author, _summary = await categorize_resource(
            title=record.get("title"), url=record["url"], domain=domain, content="",
        )

        doc = build_backfill_doc(
            record["url"], categories, tags,
            "Category/tag backfill for an already-remembered manual resource",
        )
        await cognee.remember(doc, dataset_name=DATASET_NAME)

        record["categories"] = categories
        record["tags"] = tags
        if author and not record.get("author"):
            record["author"] = author
        changed = True

        backfill_progress[key] = {"url": record["url"], "categories": categories, "tags": tags, "author": author}
        save_json(BACKFILL_PROGRESS_PATH, backfill_progress)
        print(f"  [manual:{record['id']}] {record['url']} -> {categories} {tags}")
        done += 1

    if changed:
        save_json(MANUAL_RESOURCES_PATH, manual)
    return done


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--whatsapp-limit", type=int, default=10)
    parser.add_argument("--manual-limit", type=int, default=3)
    args = parser.parse_args()

    backfill_progress = load_json(BACKFILL_PROGRESS_PATH, {})

    await connect_cognee()
    try:
        wa_done = await backfill_whatsapp(args.whatsapp_limit, backfill_progress)
        manual_done = await backfill_manual(args.manual_limit, backfill_progress)
    finally:
        await cognee.disconnect()

    print("\n=== Summary ===")
    print(f"WhatsApp backfilled: {wa_done}")
    print(f"Manual backfilled: {manual_done}")
    print(f"Progress file: {BACKFILL_PROGRESS_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
