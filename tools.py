"""
tools.py

The three required FitFindr tools plus one stretch tool. Each tool is a
standalone function that can be called and tested independently before
being wired into the agent loop.

Tools:
    search_listings(description, size, max_price)  → list[dict]
    suggest_outfit(new_item, wardrobe)              → str
    create_fit_card(outfit, new_item)               → str
    compare_price(item, all_listings)               → dict  [stretch]
"""

import os
import re

from dotenv import load_dotenv
from groq import Groq

from utils.data_loader import load_listings

load_dotenv()


# ── Groq client ───────────────────────────────────────────────────────────────

def _get_groq_client():
    """Initialize and return a Groq client using GROQ_API_KEY from .env."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY not set. Add it to a .env file in the project root."
        )
    return Groq(api_key=api_key)


# ── Tool 1: search_listings ───────────────────────────────────────────────────

def search_listings(
    description: str,
    size: str | None = None,
    max_price: float | None = None,
) -> list[dict]:
    """
    Search the mock listings dataset for items matching the description,
    optional size, and optional price ceiling.

    Args:
        description: Keywords describing what the user is looking for
                     (e.g., "vintage graphic tee").
        size:        Size string to filter by, or None to skip size filtering.
                     Matching is case-insensitive substring (e.g., "M" matches "S/M").
        max_price:   Maximum price (inclusive), or None to skip price filtering.

    Returns:
        A list of matching listing dicts, sorted by relevance (best match first).
        Returns an empty list if nothing matches — does NOT raise an exception.

    Each listing dict has the following fields:
        id, title, description, category, style_tags (list), size,
        condition, price (float), colors (list), brand, platform
    """
    listings = load_listings()

    # Apply hard filters first
    if max_price is not None:
        listings = [item for item in listings if item["price"] <= max_price]

    if size is not None:
        size_lower = size.lower()
        listings = [item for item in listings if size_lower in item["size"].lower()]

    if not listings:
        return []

    # Score by keyword overlap with description
    words = re.findall(r'\w+', description.lower())
    if not words:
        return listings  # no keywords to score — return all filtered results

    scored = []
    for item in listings:
        # Build a searchable text blob from relevant fields
        searchable = " ".join([
            item.get("title", ""),
            item.get("description", ""),
            item.get("category", ""),
            " ".join(item.get("style_tags", [])),
            " ".join(item.get("colors", [])),
            item.get("brand", "") or "",
        ]).lower()

        score = sum(1 for word in words if word in searchable)
        if score > 0:
            scored.append((score, item))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in scored]


# ── Tool 2: suggest_outfit ────────────────────────────────────────────────────

def suggest_outfit(new_item: dict, wardrobe: dict) -> str:
    """
    Given a thrifted item and the user's wardrobe, suggest 1–2 complete outfits.

    Args:
        new_item: A listing dict (the item the user is considering buying).
        wardrobe: A wardrobe dict with an 'items' key containing a list of
                  wardrobe item dicts. May be empty — handle this gracefully.

    Returns:
        A non-empty string with outfit suggestions.
        If the wardrobe is empty, offers general styling advice for the item
        rather than raising an exception or returning an empty string.
    """
    wardrobe_items = wardrobe.get("items", [])

    item_desc = (
        f"Item: {new_item.get('title', 'Unknown item')}\n"
        f"Category: {new_item.get('category', 'unknown')}\n"
        f"Style tags: {', '.join(new_item.get('style_tags', []))}\n"
        f"Colors: {', '.join(new_item.get('colors', []))}\n"
        f"Description: {new_item.get('description', '')}"
    )

    if not wardrobe_items:
        prompt = (
            f"You are a helpful fashion stylist specializing in thrift and secondhand fashion.\n\n"
            f"A user is considering buying this secondhand item:\n{item_desc}\n\n"
            f"They haven't told you what's in their wardrobe yet. Suggest 1–2 complete outfit ideas "
            f"built around this piece. Name specific types of garments, colors, and footwear that would "
            f"pair well with it. Describe the overall vibe or aesthetic of each outfit. "
            f"Keep it practical, specific, and conversational — not like a product description."
        )
    else:
        wardrobe_text = "\n".join(
            f"- {w.get('name', 'item')}: {w.get('category', '')}, "
            f"colors: {', '.join(w.get('colors', []))}, "
            f"style: {w.get('style', '')}"
            for w in wardrobe_items
        )
        prompt = (
            f"You are a helpful fashion stylist specializing in thrift and secondhand fashion.\n\n"
            f"A user is considering buying this secondhand item:\n{item_desc}\n\n"
            f"Their current wardrobe includes:\n{wardrobe_text}\n\n"
            f"Suggest 1–2 complete outfit combinations using the new item and specific pieces "
            f"from their wardrobe above. Name the wardrobe pieces by name. Describe how to wear "
            f"each combination — styling tips, layering, etc. "
            f"Keep it conversational, specific, and practical. Capture the vibe of each outfit."
        )

    try:
        client = _get_groq_client()
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=400,
        )
        result = response.choices[0].message.content.strip()
        return result if result else _suggest_outfit_fallback(new_item)
    except Exception:
        return _suggest_outfit_fallback(new_item)


def _suggest_outfit_fallback(new_item: dict) -> str:
    tags = ", ".join(new_item.get("style_tags", []))
    return (
        f"Unable to generate outfit suggestions right now. "
        f"This {new_item.get('title', 'item')} has a {tags} aesthetic — "
        f"it would pair well with basics like a plain tee, straight-leg jeans, "
        f"or neutral sneakers depending on the occasion."
    )


# ── Tool 3: create_fit_card ───────────────────────────────────────────────────

def create_fit_card(outfit: str, new_item: dict) -> str:
    """
    Generate a short, shareable outfit caption for the thrifted find.

    Args:
        outfit:   The outfit suggestion string from suggest_outfit().
        new_item: The listing dict for the thrifted item.

    Returns:
        A 2–4 sentence string usable as an Instagram/TikTok caption.
        If outfit is empty or missing, returns a descriptive error message
        string — does NOT raise an exception.
    """
    if not outfit or not outfit.strip():
        return (
            "Unable to create fit card: the outfit suggestion is missing. "
            "Please search for an item first so I have styling context to work with."
        )

    title = new_item.get("title", "this thrifted find")
    price = new_item.get("price", "?")
    platform = new_item.get("platform", "a thrift app")

    prompt = (
        f"You are writing an Instagram/TikTok OOTD caption for a thrift find.\n\n"
        f"The item: {title}, bought for ${price} on {platform}.\n"
        f"The outfit: {outfit}\n\n"
        f"Write a 2–4 sentence caption that:\n"
        f"- Sounds casual, authentic, and like a real person posting their outfit — NOT a product description\n"
        f"- Mentions the item name, price (${price}), and platform ({platform}) naturally, once each\n"
        f"- Captures the vibe or aesthetic of the outfit in specific terms\n"
        f"- Uses lowercase and feels like an actual social media post\n"
        f"- Does NOT start with 'I' or sound like an ad\n\n"
        f"Write only the caption text. No hashtags, no intro, no explanation."
    )

    try:
        client = _get_groq_client()
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.9,
            max_tokens=200,
        )
        result = response.choices[0].message.content.strip()
        return result if result else _fit_card_fallback(new_item)
    except Exception:
        return _fit_card_fallback(new_item)


def _fit_card_fallback(new_item: dict) -> str:
    title = new_item.get("title", "this find")
    platform = new_item.get("platform", "a thrift app")
    price = new_item.get("price", "?")
    return f"just thrifted this {title} off {platform} for ${price} — tell me how to style it 👀"


# ── Tool 4: compare_price (stretch) ──────────────────────────────────────────

def compare_price(item: dict, all_listings: list[dict]) -> dict:
    """
    Evaluate whether an item's price is fair relative to comparable listings.

    Args:
        item:         The listing dict to evaluate.
        all_listings: The full dataset loaded via load_listings().

    Returns:
        A dict with keys:
            assessment (str):      "below average", "fair", or "above average"
            comparable_avg (float): Mean price of comparable items
            comparable_count (int): Number of comparable items used
            verdict (str):         Human-readable one-sentence summary
    """
    category = item.get("category", "")
    item_price = item.get("price", 0.0)

    # Compare against items in the same category, excluding the item itself
    comparables = [
        lst for lst in all_listings
        if lst.get("category") == category and lst.get("id") != item.get("id")
    ]

    if not comparables:
        return {
            "assessment": "unknown",
            "comparable_avg": 0.0,
            "comparable_count": 0,
            "verdict": "Not enough comparable listings to assess this price.",
        }

    avg = sum(lst["price"] for lst in comparables) / len(comparables)

    if item_price < avg * 0.8:
        assessment = "below average"
    elif item_price > avg * 1.2:
        assessment = "above average"
    else:
        assessment = "fair"

    verdict = (
        f"This ${item_price:.0f} {category[:-1] if category.endswith('s') else category} "
        f"is {assessment} for {category} in this dataset, "
        f"where similar items average ${avg:.0f} "
        f"(based on {len(comparables)} comparable listings)."
    )

    return {
        "assessment": assessment,
        "comparable_avg": round(avg, 2),
        "comparable_count": len(comparables),
        "verdict": verdict,
    }
