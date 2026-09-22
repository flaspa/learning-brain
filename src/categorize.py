"""Lightweight categorization/tagging for Learning Brain resources.

Uses the same cheap Bedrock model already wired up in agent.py (no separate
model pipeline) via Strands' structured_output_async, given a short prompt
built from title/URL/domain/note/content excerpt. Never raises -- falls back
to a safe default so ingestion never breaks on a classification hiccup.
"""

from pydantic import BaseModel
from strands import Agent

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
                "topics mentioned). Be concise and decisive."
            ),
        )
    return _classifier


async def categorize_resource(*, title=None, url="", domain="", note=None, content=""):
    """Return (categories, tags) for a resource. Never raises."""
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
        return categories, tags
    except Exception:
        return ["Other"], []
