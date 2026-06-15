"""
tests/test_tools.py

Pytest tests for each tool's core behavior and failure modes.
Run with: pytest tests/ -v

Note: suggest_outfit and create_fit_card LLM-path tests require a live
GROQ_API_KEY — those are marked with @pytest.mark.integration and can be
skipped in CI with: pytest tests/ -v -m "not integration"
"""

import pytest

from tools import search_listings, create_fit_card, compare_price
from utils.data_loader import load_listings, get_empty_wardrobe, get_example_wardrobe


# ── search_listings ───────────────────────────────────────────────────────────

def test_search_returns_results():
    """Happy path: a broad query with loose constraints should find items."""
    results = search_listings("vintage graphic tee", size=None, max_price=50)
    assert isinstance(results, list)
    assert len(results) > 0


def test_search_returns_list_of_dicts():
    """Results should be a list of dicts with expected fields."""
    results = search_listings("jacket", size=None, max_price=None)
    assert isinstance(results, list)
    if results:
        item = results[0]
        assert "id" in item
        assert "title" in item
        assert "price" in item
        assert "platform" in item


def test_search_empty_results_no_exception():
    """An impossible query should return an empty list, not raise."""
    results = search_listings("designer ballgown", size="XXS", max_price=5)
    assert results == []


def test_search_price_filter():
    """All returned items must have price <= max_price."""
    results = search_listings("jacket", size=None, max_price=30)
    assert isinstance(results, list)
    for item in results:
        assert item["price"] <= 30, f"Item '{item['title']}' has price ${item['price']} > $30"


def test_search_size_filter_case_insensitive():
    """Size filter should be case-insensitive substring match."""
    results_upper = search_listings("tee", size="M", max_price=None)
    results_lower = search_listings("tee", size="m", max_price=None)
    assert len(results_upper) == len(results_lower)


def test_search_none_params_no_exception():
    """Passing None for both optional params should never raise."""
    results = search_listings("anything", size=None, max_price=None)
    assert isinstance(results, list)


def test_search_results_sorted_by_relevance():
    """The most relevant result should have a higher match count than later ones."""
    results = search_listings("vintage graphic tee band", size=None, max_price=None)
    if len(results) >= 2:
        # Can't directly check scores, but the first result must contain at least
        # one of the query words in its searchable fields
        first = results[0]
        searchable = (
            first["title"] + " " + first["description"] + " " +
            " ".join(first.get("style_tags", []))
        ).lower()
        query_words = ["vintage", "graphic", "tee", "band"]
        assert any(w in searchable for w in query_words)


def test_search_no_results_for_absurd_query():
    """A nonsense query under $0.01 should return empty list."""
    results = search_listings("xyzzy frobnicat quux", size=None, max_price=0.01)
    assert results == []


# ── create_fit_card ───────────────────────────────────────────────────────────

def test_create_fit_card_empty_outfit_returns_error_string():
    """Empty outfit string must return a descriptive error string, not raise."""
    item = load_listings()[0]
    result = create_fit_card("", item)
    assert isinstance(result, str)
    assert len(result) > 0
    assert "Unable to create fit card" in result or "outfit" in result.lower()


def test_create_fit_card_whitespace_outfit_returns_error_string():
    """Whitespace-only outfit string must return a descriptive error string."""
    item = load_listings()[0]
    result = create_fit_card("   ", item)
    assert isinstance(result, str)
    assert len(result) > 0


def test_create_fit_card_empty_outfit_does_not_raise():
    """create_fit_card with empty outfit must never raise an exception."""
    item = load_listings()[0]
    try:
        result = create_fit_card("", item)
        assert result is not None
    except Exception as e:
        pytest.fail(f"create_fit_card raised an exception on empty outfit: {e}")


# ── compare_price ─────────────────────────────────────────────────────────────

def test_compare_price_returns_dict():
    """compare_price should always return a dict with the expected keys."""
    listings = load_listings()
    item = listings[0]
    result = compare_price(item, listings)
    assert isinstance(result, dict)
    assert "assessment" in result
    assert "comparable_avg" in result
    assert "comparable_count" in result
    assert "verdict" in result


def test_compare_price_assessment_values():
    """Assessment should be one of the three valid values."""
    listings = load_listings()
    item = listings[0]
    result = compare_price(item, listings)
    assert result["assessment"] in ("below average", "fair", "above average", "unknown")


def test_compare_price_no_comparables():
    """An item with a unique category should return 'unknown' gracefully."""
    listings = load_listings()
    fake_item = {
        "id": "fake_001",
        "title": "Unicorn Onesie",
        "category": "unicorn_category_xyz",
        "price": 99.99,
    }
    result = compare_price(fake_item, listings)
    assert result["assessment"] == "unknown"
    assert result["comparable_count"] == 0


def test_compare_price_excludes_self():
    """The item being evaluated should not be included in its own comparison set."""
    listings = load_listings()
    item = listings[0]
    result = compare_price(item, listings)
    # comparable_count should be (items in same category - 1 for self)
    same_category = [l for l in listings if l["category"] == item["category"]]
    expected_count = len(same_category) - 1
    assert result["comparable_count"] == expected_count


# ── suggest_outfit (no-LLM failure mode only) ─────────────────────────────────

def test_suggest_outfit_empty_wardrobe_does_not_raise():
    """suggest_outfit with empty wardrobe must not raise — requires Groq key."""
    pytest.importorskip("groq")
    import os
    if not os.environ.get("GROQ_API_KEY"):
        pytest.skip("GROQ_API_KEY not set — skipping live LLM test")

    from tools import suggest_outfit
    listings = load_listings()
    result = suggest_outfit(listings[0], get_empty_wardrobe())
    assert isinstance(result, str)
    assert len(result) > 0
