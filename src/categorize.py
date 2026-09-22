"""Lightweight categorization/tagging/summarization for Learning Brain resources.

Uses the same cheap Bedrock model already wired up in agent.py (no separate
model pipeline) via Strands' structured_output_async, given a short prompt
built from title/URL/domain/note/content excerpt. One call produces
categories, tags, an optional detected author, and an optional short summary
(empty when there isn't enough content) -- extending the existing call
instead of adding new LLM round-trips. Never raises -- falls back to a safe
default so ingestion never breaks on a classification hiccup.
"""

import re

from pydantic import BaseModel
from strands import Agent

# Cheap, zero-LLM fallback for author detection from URL slugs, used when the
# model doesn't identify one (e.g. no content excerpt was available).
_LINKEDIN_AUTHOR_RE = re.compile(r"linkedin\.com/posts/([a-z0-9-]+?)-\d+", re.IGNORECASE)
_GITHUB_AUTHOR_RE = re.compile(r"github\.com/([^/]+)/")


def guess_author_from_url(url):
    if not url:
        return ""
    match = _LINKEDIN_AUTHOR_RE.search(url)
    if match:
        return match.group(1).replace("-", " ").title()
    match = _GITHUB_AUTHOR_RE.search(url)
    if match:
        return match.group(1)
    return ""

# Same model id as agent.py's MODEL_ID -- duplicated (not imported) to avoid a
# circular import, since agent.py imports categorize_resource from this module.
MODEL_ID = "us.amazon.nova-lite-v1:0"

CATEGORIES = [
    "AI / Machine Learning",
    "LLMs / Foundation Models",
    "Agents",
    "Computer Vision",
    "RAG / Knowledge / Memory",
    "Robotics / Embodied AI",
    "Data / Infrastructure",
    "Research / Papers",
    "Developer Tools / GitHub",
    "Events / Hackathons",
    "Business / Strategy",
    "Design / Creative",
    "Other",
]

CONTENT_EXCERPT_CHARS = 1500
MAX_TAGS = 5

_classifier = None


class Categorization(BaseModel):
    categories: list[str]
    tags: list[str]
    author: str = ""
    summary: str = ""


def _get_classifier():
    global _classifier
    if _classifier is None:
        _classifier = Agent(
            model=MODEL_ID,
            system_prompt=(
                "You are a fast content classifier for a personal learning archive. "
                "Given a resource's title, URL, domain, and a short excerpt, assign 1-3 "
                f"categories from this fixed list only: {', '.join(CATEGORIES)}. "
                "Also produce up to 5 short free-form tags (specific tools, models, or "
                "topics mentioned). If the author, creator, or poster's name is "
                "identifiable from the title/URL/excerpt, return it in 'author' (empty "
                "string if not identifiable -- never guess). If the excerpt has enough "
                "real content, write a 2-4 sentence 'summary' of what the resource is "
                "about; if the excerpt says no content is available or is too thin to "
                "summarize, return an empty string for 'summary' -- never invent one. "
                "Be concise and decisive."
            ),
        )
    return _classifier


async def categorize_resource(*, title=None, url="", domain="", note=None, content=""):
    """Return (categories, tags, author, summary) for a resource. Never raises."""
    excerpt = (content or "")[:CONTENT_EXCERPT_CHARS]
    prompt = "\n".join([
        f"Title: {title or '(unknown)'}",
        f"URL: {url}",
        f"Domain: {domain}",
        f"Note/context: {note or '(none)'}",
        "Excerpt:",
        excerpt or "(no content excerpt available)",
    ])
    try:
        result = await _get_classifier().structured_output_async(Categorization, prompt)
        categories = [c for c in result.categories if c in CATEGORIES] or ["Other"]
        tags = [t.strip() for t in result.tags if t and t.strip()][:MAX_TAGS]
        author = (result.author or "").strip() or guess_author_from_url(url)
        summary = (result.summary or "").strip()
        return categories, tags, author, summary
    except Exception:
        return ["Other"], [], guess_author_from_url(url), ""
