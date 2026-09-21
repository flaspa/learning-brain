"""Build a small, domain-diverse sample of parsed WhatsApp links for Bright Data testing.

Reads output/whatsapp_links.json (produced by parse_whatsapp.py) and writes
output/sample_resources.json. Does not modify the input file.
"""

import json
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlsplit

INPUT_PATH = Path("output/whatsapp_links.json")
OUTPUT_PATH = Path("output/sample_resources.json")
SAMPLE_SIZE = 20

# Priority order requested for the sample, most important first.
CATEGORY_PRIORITY = ["linkedin", "github", "event", "article", "paper", "other"]

KNOWN_DOMAIN_CATEGORIES = {
    "linkedin.com": "linkedin",
    "github.com": "github",
    "gist.github.com": "github",
    "arxiv.org": "paper",
    "paperswithcode.com": "paper",
    "openreview.net": "paper",
    "aclanthology.org": "paper",
    "semanticscholar.org": "paper",
    "biorxiv.org": "paper",
    "ssrn.com": "paper",
    "eventbrite.com": "event",
    "meetup.com": "event",
    "devpost.com": "event",
    "lu.ma": "event",
    "partiful.com": "event",
    "medium.com": "article",
    "substack.com": "article",
    "dev.to": "article",
    "hashnode.com": "article",
    "towardsdatascience.com": "article",
}

# Substring fallbacks for domains not in the exact-match table above.
CATEGORY_KEYWORDS = {
    "event": ["hackathon", "meetup", "eventbrite", "conference", "summit"],
    "article": ["blog", "medium", "substack", "tldr"],
    "paper": ["arxiv", "research"],
}


def get_domain(url):
    netloc = urlsplit(url).netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[len("www."):]
    return netloc


def categorize(domain):
    if domain in KNOWN_DOMAIN_CATEGORIES:
        return KNOWN_DOMAIN_CATEGORIES[domain]
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(keyword in domain for keyword in keywords):
            return category
    return "other"


def load_records(path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def build_sample(records):
    by_domain = defaultdict(list)
    for record in records:
        domain = get_domain(record["url"])
        by_domain[domain].append(record)

    domain_counts = Counter({domain: len(recs) for domain, recs in by_domain.items()})

    # Domains grouped by category, most-common domain first within each category.
    domains_by_category = defaultdict(list)
    for domain in by_domain:
        domains_by_category[categorize(domain)].append(domain)
    for category, domains in domains_by_category.items():
        domains.sort(key=lambda d: (-domain_counts[d], d))

    # Round-robin across categories (in priority order) so no single broad
    # category (e.g. "article") crowds out the others before the sample fills.
    queues = [domains_by_category[c] for c in CATEGORY_PRIORITY if c in domains_by_category]
    cursors = [0] * len(queues)

    sample = []
    selected_domains = []
    progressed = True
    while len(sample) < SAMPLE_SIZE and progressed:
        progressed = False
        for i, queue in enumerate(queues):
            if len(sample) >= SAMPLE_SIZE:
                break
            if cursors[i] < len(queue):
                domain = queue[cursors[i]]
                cursors[i] += 1
                # First record per domain, in original (chronological) order.
                sample.append(by_domain[domain][0])
                selected_domains.append(domain)
                progressed = True

    return sample, domain_counts, selected_domains


def main():
    records = load_records(INPUT_PATH)
    sample, domain_counts, selected_domains = build_sample(records)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(sample, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"Loaded {len(records)} records from {INPUT_PATH}")
    print(f"Found {len(domain_counts)} distinct domains")
    print("Top domains:")
    for domain, count in domain_counts.most_common(15):
        print(f"  {domain}: {count}")

    print(f"\nSelected {len(sample)} sample records across {len(selected_domains)} domains:")
    for domain in selected_domains:
        print(f"  {domain} (category: {categorize(domain)}, total in dataset: {domain_counts[domain]})")

    print(f"\nOutput written to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
