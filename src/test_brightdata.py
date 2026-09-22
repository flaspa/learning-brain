"""Bright Data smoke test: fetch 5 representative sample URLs.

Uses the Bright Data Web Unlocker REST API (POST https://api.brightdata.com/request,
Bearer auth, JSON body {zone, url, format}) to fetch public page content for one
LinkedIn, one GitHub, one arXiv, one event/hackathon, and one article/blog URL
selected from output/sample_resources.json. See CLAUDE.md.
"""

import json
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

from sample_resources import categorize, get_domain

SAMPLE_INPUT_PATH = Path("output/sample_resources.json")
OUTPUT_PATH = Path("output/brightdata_test.json")
BRIGHTDATA_ENDPOINT = "https://api.brightdata.com/request"
MAX_URLS = 5
CONSOLE_PREVIEW_CHARS = 200
REQUEST_TIMEOUT_SECONDS = 60


def load_credentials():
    load_dotenv()
    api_key = os.getenv("BRIGHTDATA_API_KEY")
    zone = os.getenv("BRIGHTDATA_ZONE")
    if not api_key or not zone:
        print("Missing BRIGHTDATA_API_KEY or BRIGHTDATA_ZONE in .env", file=sys.stderr)
        sys.exit(1)
    return api_key, zone


def load_sample(path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def is_arxiv(domain):
    return domain == "arxiv.org" or domain.endswith(".arxiv.org")


def select_test_records(records):
    """Pick one record each for LinkedIn, GitHub, arXiv, event/hackathon, article/blog."""
    wanted = [
        ("linkedin", lambda d: categorize(d) == "linkedin"),
        ("github", lambda d: categorize(d) == "github"),
        ("arxiv", is_arxiv),
        ("event", lambda d: categorize(d) == "event"),
        ("article", lambda d: categorize(d) == "article"),
    ]
    selected = []
    used_ids = set()
    for label, predicate in wanted:
        for record in records:
            if record["id"] in used_ids:
                continue
            if predicate(get_domain(record["url"])):
                selected.append((label, record))
                used_ids.add(record["id"])
                break
    return selected[:MAX_URLS]


def fetch_url(session, api_key, zone, url):
    """Fetch one public URL via Bright Data. Returns (fields_dict, is_auth_failure)."""
    try:
        response = session.post(
            BRIGHTDATA_ENDPOINT,
            headers={"Authorization": f"Bearer {api_key}"},
            json={"zone": zone, "url": url, "format": "json"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        return {
            "fetch_status": "error",
            "http_status": None,
            "resolved_url": url,
            "content_type": None,
            "fetched_text": None,
            "fetch_error": f"request failed: {exc}",
        }, False

    if response.status_code in (401, 403):
        return {
            "fetch_status": "auth_failed",
            "http_status": response.status_code,
            "resolved_url": url,
            "content_type": None,
            "fetched_text": None,
            "fetch_error": "Bright Data authentication failed",
        }, True

    if response.status_code != 200:
        return {
            "fetch_status": "error",
            "http_status": response.status_code,
            "resolved_url": url,
            "content_type": None,
            "fetched_text": None,
            "fetch_error": f"Bright Data gateway returned HTTP {response.status_code}",
        }, False

    try:
        payload = response.json()
    except ValueError:
        return {
            "fetch_status": "error",
            "http_status": response.status_code,
            "resolved_url": url,
            "content_type": None,
            "fetched_text": None,
            "fetch_error": "could not decode Bright Data JSON response",
        }, False

    target_status = payload.get("status_code", payload.get("status"))
    headers = payload.get("headers") or {}
    content_type = headers.get("content-type") or headers.get("Content-Type")
    body = payload.get("body", "")

    if target_status and target_status >= 400:
        return {
            "fetch_status": "error",
            "http_status": target_status,
            "resolved_url": url,
            "content_type": content_type,
            "fetched_text": None,
            "fetch_error": f"target page returned HTTP {target_status}",
        }, False

    # Bright Data's Web Unlocker follows redirects itself and reports where it
    # landed via this header -- the existing fetch already resolves short
    # links/tracking URLs to the final page; we just weren't reading it.
    resolved_url = headers.get("x-unblocker-redirected-to") or headers.get("X-Unblocker-Redirected-To") or url

    return {
        "fetch_status": "success",
        "http_status": target_status,
        "resolved_url": resolved_url,
        "content_type": content_type,
        "fetched_text": body,
        "fetch_error": None,
    }, False


def console_preview(text):
    if not text:
        return ""
    text = text.replace("\n", " ")
    return text[:CONSOLE_PREVIEW_CHARS] + ("..." if len(text) > CONSOLE_PREVIEW_CHARS else "")


def main():
    api_key, zone = load_credentials()
    records = load_sample(SAMPLE_INPUT_PATH)
    selected = select_test_records(records)

    if not selected:
        print("No matching records found in sample_resources.json for the required categories.")
        sys.exit(1)

    print(f"Selected {len(selected)} of {MAX_URLS} target records:")
    for label, record in selected:
        print(f"  [{label}] id={record['id']} domain={get_domain(record['url'])}")

    session = requests.Session()
    results = []

    for label, record in selected:
        print(f"\nFetching [{label}] id={record['id']} ...")
        fields, is_auth_failure = fetch_url(session, api_key, zone, record["url"])

        if is_auth_failure:
            print("Bright Data authentication failed. Check BRIGHTDATA_API_KEY and BRIGHTDATA_ZONE.")
            print("Stopping without writing output/brightdata_test.json.")
            sys.exit(1)

        print(f"  fetch_status={fields['fetch_status']} http_status={fields['http_status']}")
        if fields["fetched_text"]:
            print(f"  preview: {console_preview(fields['fetched_text'])}")
        if fields["fetch_error"]:
            print(f"  fetch_error: {fields['fetch_error']}")

        output_record = dict(record)
        output_record.update(fields)
        results.append(output_record)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"\nWrote {len(results)} results to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
