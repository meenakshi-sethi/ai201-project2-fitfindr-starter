"""
agent.py

The FitFindr planning loop. Orchestrates the three tools in response to a
natural language user query, passing state between them via a session dict.

Usage:
    from agent import run_agent
    from utils.data_loader import get_example_wardrobe

    result = run_agent(
        query="vintage graphic tee under $30, size M",
        wardrobe=get_example_wardrobe(),
    )
    print(result["fit_card"])
    print(result["error"])   # None on success
"""

import json
import os
import re

from dotenv import load_dotenv
from groq import Groq

from tools import search_listings, suggest_outfit, create_fit_card, compare_price
from utils.data_loader import load_listings

load_dotenv()


# ── session state ─────────────────────────────────────────────────────────────

def _new_session(query: str, wardrobe: dict) -> dict:
    """
    Initialize and return a fresh session dict for one user interaction.

    The session dict is the single source of truth for everything that happens
    during a run — it stores the original query, parsed parameters, tool results,
    and any error that caused early termination.
    """
    return {
        "query": query,              # original user query
        "parsed": {},                # extracted description / size / max_price
        "search_results": [],        # list of matching listing dicts
        "selected_item": None,       # top result, passed into suggest_outfit
        "wardrobe": wardrobe,        # user's wardrobe dict
        "outfit_suggestion": None,   # string returned by suggest_outfit
        "fit_card": None,            # string returned by create_fit_card
        "error": None,               # set if the interaction ended early
        "retry_attempted": False,    # True if search was retried with looser filters
        "price_assessment": None,    # dict from compare_price (stretch)
    }


# ── query parser ──────────────────────────────────────────────────────────────

def _parse_query(query: str) -> dict:
    """
    Use the Groq LLM to extract description, size, and max_price from a
    natural language query. Falls back to using the full query as description
    if parsing fails.

    Returns:
        dict with keys: description (str), size (str | None), max_price (float | None)
    """
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return {"description": query, "size": None, "max_price": None}

    prompt = (
        "Extract search parameters from this thrift shopping query. "
        "Return ONLY a JSON object with exactly these keys:\n"
        '  "description": a short keyword description of the item (str)\n'
        '  "size": clothing size if mentioned, else null\n'
        '  "max_price": maximum price as a number if mentioned, else null\n\n'
        f"Query: {query}\n\n"
        "Return only the JSON, no explanation."
    )

    try:
        client = Groq(api_key=api_key)
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=100,
        )
        raw = response.choices[0].message.content.strip()

        # Extract JSON from response (may be wrapped in markdown)
        json_match = re.search(r'\{.*\}', raw, re.DOTALL)
        if json_match:
            parsed = json.loads(json_match.group())
            description = parsed.get("description") or query
            size = parsed.get("size")
            max_price_raw = parsed.get("max_price")
            max_price = float(max_price_raw) if max_price_raw is not None else None
            return {"description": description, "size": size, "max_price": max_price}
    except Exception:
        pass

    # Fallback: use full query as description, try regex for price
    price_match = re.search(r'\$?(\d+(?:\.\d+)?)', query)
    max_price = float(price_match.group(1)) if price_match else None
    return {"description": query, "size": None, "max_price": max_price}


# ── planning loop ─────────────────────────────────────────────────────────────

def run_agent(query: str, wardrobe: dict) -> dict:
    """
    Main agent entry point. Runs the FitFindr planning loop for a single
    user interaction and returns the completed session dict.

    Args:
        query:    Natural language user request
                  (e.g., "vintage graphic tee under $30, size M")
        wardrobe: User's wardrobe dict — use get_example_wardrobe() or
                  get_empty_wardrobe() from utils/data_loader.py

    Returns:
        The session dict after the interaction completes. Check session["error"]
        first — if it is not None, the interaction ended early and the other
        output fields (outfit_suggestion, fit_card) will be None.
    """
    # Step 1: Initialize session
    session = _new_session(query, wardrobe)

    # Step 2: Parse the user's query to extract description, size, max_price
    parsed = _parse_query(query)
    session["parsed"] = parsed
    description = parsed["description"]
    size = parsed["size"]
    max_price = parsed["max_price"]

    # Step 3: Call search_listings with parsed parameters
    results = search_listings(description, size=size, max_price=max_price)
    session["search_results"] = results

    # If no results, attempt retry with loosened constraints (stretch: retry logic)
    if not results:
        had_filters = size is not None or max_price is not None
        if had_filters:
            session["retry_attempted"] = True
            loosened_max_price = (max_price * 1.5) if max_price is not None else None
            results = search_listings(description, size=None, max_price=loosened_max_price)
            session["search_results"] = results

            if results:
                # Inform user what was adjusted
                adjustments = []
                if size is not None:
                    adjustments.append("removed the size filter")
                if max_price is not None:
                    adjustments.append(f"raised the price ceiling to ${loosened_max_price:.0f}")
                adjustment_note = " and ".join(adjustments)
                session["retry_note"] = (
                    f"No exact matches found — I {adjustment_note} and found these instead."
                )
            else:
                # Both attempts failed — return early with helpful error
                price_hint = f" under ${max_price:.0f}" if max_price else ""
                size_hint = f" in size {size}" if size else ""
                session["error"] = (
                    f"No listings found for '{description}'{size_hint}{price_hint}, "
                    f"even after loosening the filters. "
                    f"Try broader keywords, a different size, or a higher price ceiling."
                )
                return session
        else:
            # No filters to loosen — return early
            session["error"] = (
                f"No listings found for '{description}'. "
                f"Try different keywords — for example, 'vintage tee' instead of a very specific term."
            )
            return session

    # Step 4: Select top result as the item to style
    session["selected_item"] = results[0]

    # Step 5: Price comparison (stretch tool)
    try:
        all_listings = load_listings()
        session["price_assessment"] = compare_price(session["selected_item"], all_listings)
    except Exception:
        session["price_assessment"] = None

    # Step 6: Suggest outfit using selected item and user's wardrobe
    session["outfit_suggestion"] = suggest_outfit(
        session["selected_item"],
        session["wardrobe"],
    )

    # Step 7: Generate fit card from outfit suggestion and selected item
    session["fit_card"] = create_fit_card(
        session["outfit_suggestion"],
        session["selected_item"],
    )

    # Step 8: Return completed session
    return session


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from utils.data_loader import get_example_wardrobe, get_empty_wardrobe

    print("=== Happy path: graphic tee ===\n")
    session = run_agent(
        query="looking for a vintage graphic tee under $30",
        wardrobe=get_example_wardrobe(),
    )
    if session["error"]:
        print(f"Error: {session['error']}")
    else:
        if session.get("retry_note"):
            print(f"Note: {session['retry_note']}\n")
        print(f"Found: {session['selected_item']['title']} — ${session['selected_item']['price']}")
        if session.get("price_assessment"):
            print(f"Price check: {session['price_assessment']['verdict']}")
        print(f"\nOutfit: {session['outfit_suggestion']}")
        print(f"\nFit card: {session['fit_card']}")

    print("\n\n=== No-results path ===\n")
    session2 = run_agent(
        query="designer ballgown size XXS under $5",
        wardrobe=get_example_wardrobe(),
    )
    print(f"Error message: {session2['error']}")
    print(f"Retry attempted: {session2['retry_attempted']}")

    print("\n\n=== Empty wardrobe path ===\n")
    session3 = run_agent(
        query="vintage denim jacket",
        wardrobe=get_empty_wardrobe(),
    )
    if session3["error"]:
        print(f"Error: {session3['error']}")
    else:
        print(f"Found: {session3['selected_item']['title']}")
        print(f"\nOutfit (general advice): {session3['outfit_suggestion']}")
        print(f"\nFit card: {session3['fit_card']}")
