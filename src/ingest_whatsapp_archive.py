"""Resumable bulk ingestion of the WhatsApp link archive into Cognee Cloud.

Reuses existing, proven pieces only:
- Bright Data fetch: test_brightdata.load_credentials / fetch_url
- Cognee Cloud connection: cognee_memory.connect_cognee / DATASET_NAME
- HTML-to-text + truncation: test_cognee.html_to_text / FETCHED_TEXT_CHAR_LIMIT
- domain/category: sample_resources.get_domain / categorize

Sequential (no concurrency). Progress is written to output/ after every record
so a run can be interrupted and resumed: records already marked "success" in
the progress file are skipped; a failed record is logged once and the script
moves on -- it is not retried within the same run, but will be reattempted on
a later run since only "success" is skipped.

CLI:
    python src/ingest_whatsapp_archive.py --limit 25
    python src/ingest_whatsapp_archive.py
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import cognee
import requests

from cognee_memory import DATASET_NAME, connect_cognee
from sample_resources import categorize, get_domain
from test_brightdata import fetch_url, load_credentials
from test_cognee import FETCHED_TEXT_CHAR_LIMIT, html_to_text

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

INPUT_PATH = Path("output/whatsapp_links.json")
PROGRESS_PATH = Path("output/whatsapp_ingest_progress.json")
RAW_MESSAGE_CHAR_LIMIT = 300


def load_records():
    with INPUT_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_progress():
    if PROGRESS_PATH.exists():
        with PROGRESS_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_progress(progress):
    PROGRESS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with PROGRESS_PATH.open("w", encoding="utf-8") as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)


def build_memory_text(record, fetched_text):
    domain = get_domain(record["url"])
    category = categorize(domain)
    raw_message = (record.get("raw_message") or "").strip()
    if len(raw_message) > RAW_MESSAGE_CHAR_LIMIT:
        raw_message = raw_message[:RAW_MESSAGE_CHAR_LIMIT] + "..."

    body = html_to_text(fetched_text)
    if len(body) > FETCHED_TEXT_CHAR_LIMIT:
        body = body[:FETCHED_TEXT_CHAR_LIMIT] + "..."

    return "\n".join([
        f"URL: {record['url']}",
        f"Timestamp: {record.get('timestamp')}",
        f"Note before: {record.get('note_before') or '(none)'}",
        f"Note after: {record.get('note_after') or '(none)'}",
        f"Source: {record.get('source')}",
        f"Domain: {domain}",
        f"Category: {category}",
        f"Raw message: {raw_message or '(none)'}",
        "Content:",
        body,
    ])


async def ingest_one(session, api_key, zone, record):
    fields, auth_failed = fetch_url(session, api_key, zone, record["url"])
    if auth_failed:
        return "failed", "Bright Data authentication failed"
    if fields["fetch_status"] != "success":
        return "failed", fields.get("fetch_error") or fields["fetch_status"]

    memory_text = build_memory_text(record, fields["fetched_text"])
    try:
        await cognee.remember(memory_text, dataset_name=DATASET_NAME)
    except Exception as exc:
        return "failed", f"{type(exc).__name__}: {exc}"

    return "success", None


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="max records to attempt this run")
    args = parser.parse_args()

    records = load_records()
    progress = load_progress()
    print(f"Loaded {len(records)} records from {INPUT_PATH}")
    print(f"Progress file has {len(progress)} prior entries ({PROGRESS_PATH})")

    api_key, zone = load_credentials()
    session = requests.Session()

    await connect_cognee()

    attempted = succeeded = failed = skipped = 0
    try:
        for record in records:
            record_id = str(record["id"])

            if progress.get(record_id, {}).get("status") == "success":
                skipped += 1
                continue

            if args.limit is not None and attempted >= args.limit:
                break

            attempted += 1
            status, error = await ingest_one(session, api_key, zone, record)

            entry = {
                "status": status,
                "url": record["url"],
                "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            if error:
                entry["error"] = error
            progress[record_id] = entry
            save_progress(progress)

            if status == "success":
                succeeded += 1
                print(f"  [{attempted}] OK   id={record_id} {record['url']}")
            else:
                failed += 1
                print(f"  [{attempted}] FAIL id={record_id} {record['url']} -- {error}")
    finally:
        await cognee.disconnect()

    print("\n=== Summary ===")
    print(f"Attempted: {attempted}")
    print(f"Succeeded: {succeeded}")
    print(f"Failed: {failed}")
    print(f"Skipped (already ingested): {skipped}")
    print(f"Progress file: {PROGRESS_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
