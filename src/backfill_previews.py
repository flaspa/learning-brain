"""Historical preview-only backfill for already-ingested resources.

Adds rich-link preview metadata (image/title/description/site name) for
WhatsApp-archive and manual resources that were fetched successfully before
preview extraction existed -- WITHOUT re-running ingestion, categorization,
summarization, or touching Cognee. Reuses the existing Bright Data fetch
path (test_brightdata.fetch_url) and the same preview-metadata extraction
logic already used for new resources (agent.extract_preview_metadata),
inlined here so this script stays independent of the Strands/Cognee imports
agent.py pulls in. No LLM call, no new scraping stack.

Resumable: output/preview_backfill.json holds one record per URL and is
saved after every fetch. Records with status "success" are never re-fetched;
only missing or failed ones are retried on a later run.

CLI:
    python src/backfill_previews.py                # bounded test: first 5 eligible
    python src/backfill_previews.py --limit 1000    # backfill (up to) the rest
"""

import argparse
import html
import json
import re
import sys
from pathlib import Path
from urllib.parse import urljoin

import requests

from sample_resources import get_domain
from test_brightdata import fetch_url, load_credentials

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

WHATSAPP_PROGRESS_PATH = Path("output/whatsapp_ingest_progress.json")
MANUAL_RESOURCES_PATH = Path("output/manual_resources.json")
PREVIEW_BACKFILL_PATH = Path("output/preview_backfill.json")

TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
CANONICAL_RE = re.compile(r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)["\']', re.IGNORECASE)
DESCRIPTION_RE = re.compile(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']*)["\']', re.IGNORECASE)


def _meta_content_patterns(prop):
    return [
        re.compile(rf'<meta[^>]+(?:property|name)=["\']{prop}["\'][^>]+content=["\']([^"\']*)["\']', re.IGNORECASE),
        re.compile(rf'<meta[^>]+content=["\']([^"\']*)["\'][^>]+(?:property|name)=["\']{prop}["\']', re.IGNORECASE),
    ]


_META_PATTERNS = {
    "image": _meta_content_patterns("og:image") + _meta_content_patterns("twitter:image") + _meta_content_patterns("twitter:image:src"),
    "title": _meta_content_patterns("og:title") + _meta_content_patterns("twitter:title"),
    "description": _meta_content_patterns("og:description") + _meta_content_patterns("twitter:description"),
    "site_name": _meta_content_patterns("og:site_name"),
    "author": _meta_content_patterns("article:author") + _meta_content_patterns("author"),
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
    """Same field priority as agent.extract_preview_metadata: og:*/twitter:*/
    canonical/<title>/meta description, from the already-fetched final page."""
    if not raw_html:
        return {"preview_image": None, "preview_title": None, "preview_description": None,
                "preview_site_name": None, "canonical_url": None, "author": None}

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
        "author": _first_meta_match(raw_html, "author"),
    }


def load_json(path, default):
    if path.exists():
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    return default


def save_progress(progress):
    PREVIEW_BACKFILL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with PREVIEW_BACKFILL_PATH.open("w", encoding="utf-8") as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)


def collect_candidates():
    """Successful WhatsApp ingests, plus manual resources that predate
    preview extraction and still lack it. Never includes failed ingests."""
    candidates = []
    seen = set()

    for entry in load_json(WHATSAPP_PROGRESS_PATH, {}).values():
        url = entry.get("url")
        if entry.get("status") == "success" and url and url not in seen:
            candidates.append(url)
            seen.add(url)

    for record in load_json(MANUAL_RESOURCES_PATH, []):
        url = record.get("url")
        if not url or url in seen:
            continue
        if record.get("preview_image") or record.get("preview_title"):
            continue  # already has valid preview metadata -- skip
        candidates.append(url)
        seen.add(url)

    return candidates


def failed_record(url, error):
    return {
        "original_url": url, "resolved_url": None, "canonical_url": None,
        "preview_image": None, "preview_title": None, "preview_description": None,
        "preview_site_name": None, "author": None, "domain": get_domain(url),
        "status": "failed", "error": error,
    }


def fetch_preview(session, api_key, zone, url):
    fields, auth_failed = fetch_url(session, api_key, zone, url)

    # Retry once, only on a transient network-level failure (timeout, DNS,
    # connection reset) -- not on a genuine 4xx/5xx from the target page.
    if not auth_failed and fields["fetch_status"] != "success":
        err = (fields.get("fetch_error") or "").lower()
        if "timed out" in err or "request failed" in err:
            fields, auth_failed = fetch_url(session, api_key, zone, url)

    if auth_failed:
        return None, "Bright Data authentication failed"
    if fields["fetch_status"] != "success":
        return None, fields.get("fetch_error") or fields["fetch_status"]

    resolved_url = fields.get("resolved_url") or url
    preview = extract_preview_metadata(fields["fetched_text"], resolved_url)
    resolved_url = preview.get("canonical_url") or resolved_url
    return {
        "original_url": url,
        "resolved_url": resolved_url,
        "canonical_url": preview.get("canonical_url"),
        "preview_image": preview.get("preview_image"),
        "preview_title": preview.get("preview_title"),
        "preview_description": preview.get("preview_description"),
        "preview_site_name": preview.get("preview_site_name") or get_domain(resolved_url),
        "author": preview.get("author"),
        "domain": get_domain(resolved_url),
        "status": "success",
        "error": None,
    }, None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=5, help="max URLs to process this run (default 5, for a bounded test)")
    args = parser.parse_args()

    api_key, zone = load_credentials()
    session = requests.Session()

    progress = load_json(PREVIEW_BACKFILL_PATH, {})
    candidates = collect_candidates()
    eligible = [u for u in candidates if progress.get(u, {}).get("status") != "success"]
    already_done = len(candidates) - len(eligible)

    todo = eligible[: args.limit]
    print(f"{len(candidates)} candidate URLs total ({already_done} already have a successful preview backfill).")
    print(f"Processing {len(todo)} of {len(eligible)} remaining eligible URLs...")

    done, failed = 0, 0
    for i, url in enumerate(todo, 1):
        print(f"[{i}/{len(todo)}] {url}")
        record, error = fetch_preview(session, api_key, zone, url)
        progress[url] = record if record else failed_record(url, error)
        save_progress(progress)  # after every record -- resumable, nothing lost on interruption

        if record:
            done += 1
            print(f"   ok: image={bool(record['preview_image'])} title={record['preview_title'] or '(none)'}")
        else:
            failed += 1
            print(f"   failed: {error}")

    print("\n=== Summary ===")
    print(f"Eligible before this run: {len(eligible)} (of {len(candidates)} total candidates, {already_done} already done)")
    print(f"Processed this run: {len(todo)} (success={done}, failed={failed})")
    print(f"Still remaining: {len(eligible) - len(todo)}")
    print(f"Stored at: {PREVIEW_BACKFILL_PATH}")


if __name__ == "__main__":
    main()
