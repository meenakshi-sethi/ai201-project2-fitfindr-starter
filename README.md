# FitFindr

A multi-tool AI agent that helps users find secondhand fashion pieces and figure out how to wear them. FitFindr takes a natural language query, searches a dataset of thrift listings, evaluates the price, generates outfit ideas from the user's wardrobe, and creates a shareable social caption — all in a single interaction.

Built with Python, Groq (llama-3.3-70b-versatile), and Gradio.

---

## Setup

```bash
# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate  # Mac/Linux

# Install dependencies
pip install -r requirements.txt

# Create .env with your Groq API key (free at console.groq.com)
echo "GROQ_API_KEY=your_key_here" > .env
```

Run the app:
```bash
python app.py
# Open http://localhost:7860
```

Run tests:
```bash
pytest tests/ -v
```

---

## Tool Inventory

### Tool 1: `search_listings(description, size, max_price)`

| Field | Value |
|-------|-------|
| **Purpose** | Searches the mock secondhand listings dataset for items matching a keyword description, with optional size and price filters. Returns results ranked by keyword relevance. |
| **Inputs** | `description` (str) — keywords describing the item (e.g., "vintage graphic tee"); `size` (str \| None) — clothing size to filter by, case-insensitive substring match so "M" matches "S/M"; `max_price` (float \| None) — maximum price ceiling, inclusive |
| **Returns** | `list[dict]` — matching listing dicts sorted by relevance score (best match first), or `[]` if nothing matches. Each dict contains: `id` (str), `title` (str), `description` (str), `category` (str), `style_tags` (list[str]), `size` (str), `condition` (str), `price` (float), `colors` (list[str]), `brand` (str\|None), `platform` (str). |
| **Error handling** | Returns an empty list — never raises. The agent handles the empty list separately (see Planning Loop section). |

**Scoring approach:** After applying price and size filters, each remaining item is scored by counting how many of the description's words appear in a concatenation of the item's title, description, style_tags, colors, brand, and category. Items with a score of 0 are dropped. Remaining items are sorted highest-score-first.

---

### Tool 2: `suggest_outfit(new_item, wardrobe)`

| Field | Value |
|-------|-------|
| **Purpose** | Given a thrifted item and the user's wardrobe, calls the Groq LLM to suggest 1–2 complete outfit combinations using named wardrobe pieces. Falls back to general styling advice if the wardrobe is empty. |
| **Inputs** | `new_item` (dict) — a listing dict from search_listings (the item the user is considering buying); `wardrobe` (dict) — a wardrobe dict with an `'items'` key containing a list of wardrobe item dicts, each with: `name` (str), `category` (str), `colors` (list[str]), `style` (str), `notes` (str). May be an empty wardrobe. |
| **Returns** | `str` — a non-empty outfit suggestion string. When wardrobe has items: names specific wardrobe pieces and explains how to combine them with the new item. When wardrobe is empty: describes general styling advice (what types of pieces and aesthetics pair well). |
| **Error handling** | Empty wardrobe → switches to a general styling prompt (no crash). Groq API error → returns a fallback string using the item's style tags. Always returns a non-empty string. |

---

### Tool 3: `create_fit_card(outfit, new_item)`

| Field | Value |
|-------|-------|
| **Purpose** | Generates a 2–4 sentence casual Instagram/TikTok-style caption for the thrifted find and outfit. Uses a higher LLM temperature (0.9) so outputs vary across calls. |
| **Inputs** | `outfit` (str) — the outfit suggestion string from suggest_outfit; `new_item` (dict) — the listing dict for the thrifted item (used to extract title, price, and platform for the caption) |
| **Returns** | `str` — a 2–4 sentence caption that feels like an authentic social media post: mentions the item name, price, and platform once each; captures the outfit vibe in specific terms; uses lowercase; does not read like a product description. |
| **Error handling** | If `outfit` is empty or whitespace: returns a descriptive error string immediately, no LLM call made. If Groq API errors: returns a minimal fallback caption using only the item's title, platform, and price. Never raises an exception. |

---

### Tool 4: `compare_price(item, all_listings)` — Stretch

| Field | Value |
|-------|-------|
| **Purpose** | Evaluates whether an item's price is fair by comparing it to similarly-categorized listings in the same dataset. |
| **Inputs** | `item` (dict) — the listing dict to evaluate; `all_listings` (list[dict]) — the full dataset from load_listings() |
| **Returns** | `dict` with keys: `assessment` (str — "below average", "fair", or "above average"), `comparable_avg` (float — mean price of comparable items), `comparable_count` (int — number of items used), `verdict` (str — human-readable one-sentence summary like "This $24 tee is fair for tops, where similar items average $28.") |
| **How comparisons are made** | Filters the dataset to items with the same `category` as the input item (excluding the item itself), computes the mean price, then classifies: below average if price < avg × 0.8; fair if 0.8 ≤ ratio ≤ 1.2; above average if price > avg × 1.2. |
| **Error handling** | If no comparable items found: returns `{"assessment": "unknown", "comparable_count": 0, "verdict": "Not enough comparable listings to assess this price."}`. Never raises. |

---

## Planning Loop

The planning loop in `run_agent()` (`agent.py`) follows a **linear-with-branching** pattern. It does not call all tools unconditionally — its behavior depends on what each step returns.

### Step-by-step conditional logic

**Step 1 — Parse query:**
The Groq LLM extracts `description`, `size`, and `max_price` from the natural language query and returns structured JSON. If LLM parsing fails (network error, malformed JSON), the agent falls back to using the full query as the description. This step always produces output — it never causes early termination.

**Step 2 — Call `search_listings`:**
This is the critical branch point.

- If results are non-empty → store in `session["search_results"]`, select `results[0]` as `session["selected_item"]`, proceed to step 3.
- If results are empty AND at least one filter (size or max_price) was applied → **retry with loosened constraints**: drop the size filter entirely, raise max_price by 50% (or remove it if it was None). Set `session["retry_attempted"] = True`. If the retry succeeds, note what was adjusted in `session["retry_note"]` and proceed.
- If retry also returns empty, OR if no filters were applied → set `session["error"]` with a specific actionable message (describes what was searched, what was tried, and what the user can change), then **return the session immediately**. `suggest_outfit` and `create_fit_card` are never called with empty input.

**Step 3 — Call `compare_price` (stretch):**
Always runs if step 2 succeeded. Result stored in `session["price_assessment"]`. Never causes early termination.

**Step 4 — Call `suggest_outfit`:**
Always called after a successful search. Uses `session["selected_item"]` and `session["wardrobe"]` (set at initialization — the user never re-enters wardrobe data). The wardrobe may be empty (new user), in which case `suggest_outfit` switches to a general styling prompt. Result stored in `session["outfit_suggestion"]`.

**Step 5 — Call `create_fit_card`:**
Called with `session["outfit_suggestion"]` and `session["selected_item"]`. Both are guaranteed non-None at this point because the agent returned early in step 2 if search failed, and `suggest_outfit` always returns a non-empty string. Result stored in `session["fit_card"]`.

**Step 6 — Return session.**

### What makes it adaptive

The key difference from a fixed sequence: if `search_listings` returns `[]`, the agent does not call `suggest_outfit` at all — it tries a retry first, and if that fails too, it returns an error without ever invoking the LLM for outfit generation. A user searching for "designer ballgown size XXS under $5" will get a specific error message, not a hallucinated outfit suggestion for a non-existent item.

---

## State Management

All state lives in a single `session` dict initialized at the start of each `run_agent()` call. No global state is used — each call is independent.

| Session key | Set when | Used by |
|-------------|----------|---------|
| `session["query"]` | Initialization | LLM query parser |
| `session["parsed"]` | After query parse | search_listings |
| `session["search_results"]` | After search_listings | selected_item selection, display |
| `session["selected_item"]` | After search — `results[0]` | suggest_outfit, create_fit_card, compare_price |
| `session["wardrobe"]` | Initialization (passed in by caller) | suggest_outfit |
| `session["price_assessment"]` | After compare_price | app.py display only |
| `session["outfit_suggestion"]` | After suggest_outfit | create_fit_card |
| `session["fit_card"]` | After create_fit_card | app.py display only |
| `session["error"]` | On early termination | app.py: routes to error display |
| `session["retry_attempted"]` | If search retry fires | transparency, README |
| `session["retry_note"]` | If retry succeeded | app.py: shown in panel 1 |

**Key state handoffs (verified in testing):**
- `session["selected_item"]` is the exact same dict object passed into `suggest_outfit` and `create_fit_card` — no re-fetch, no re-entry.
- `session["outfit_suggestion"]` is the exact string from `suggest_outfit` passed directly into `create_fit_card` — the user never re-enters it.
- The wardrobe is stored in the session at initialization and accessed in step 4, so it never needs to be re-entered within a session.

---

## Error Handling

### Per-tool failure modes

**`search_listings` — no results:**
Returns `[]` silently. The agent handles this in the planning loop:
- First retry: loosens constraints (drops size filter, raises max_price by 50%). If retry succeeds, the agent notes what was adjusted in the output panel (e.g., "No exact matches found — I removed the size filter and raised the price ceiling to $45 and found these instead.").
- If retry also empty: agent sets `session["error"]` to a specific, actionable message and returns early. Example error message from testing: *"No listings found for 'designer ballgown' in size XXS under $5, even after loosening the filters. Try broader keywords, a different size, or a higher price ceiling."*
- `suggest_outfit` and `create_fit_card` are never called.

**`suggest_outfit` — empty wardrobe:**
Does not crash. The tool detects `wardrobe["items"] == []` and switches from a wardrobe-specific prompt to a general styling prompt. Tested manually with `get_empty_wardrobe()` — the tool returns useful styling advice regardless.

**`suggest_outfit` — Groq API error:**
Catches all exceptions and returns a fallback string that mentions the item's style tags: *"Unable to generate outfit suggestions right now. This [item title] has a [tags] aesthetic — it would pair well with basics like a plain tee, straight-leg jeans, or neutral sneakers depending on the occasion."* The agent continues to `create_fit_card` with this fallback string.

**`create_fit_card` — empty outfit string:**
Returns a descriptive error string immediately, without calling the LLM: *"Unable to create fit card: the outfit suggestion is missing. Please search for an item first so I have styling context to work with."* Tested with `create_fit_card("", item)` — confirmed it returns a non-empty string and does not raise.

**`create_fit_card` — Groq API error:**
Returns a minimal fallback caption using only the item dict's fields: *"just thrifted this [title] off [platform] for $[price] — tell me how to style it 👀"*

### Concrete test examples

From running the test suite (`pytest tests/ -v`):

```python
# Triggered failure 1: search returns empty on impossible query
results = search_listings("designer ballgown", size="XXS", max_price=5)
# → []  (no exception, no crash)

# Triggered failure 2: create_fit_card with empty outfit
result = create_fit_card("", load_listings()[0])
# → "Unable to create fit card: the outfit suggestion is missing..."

# Triggered failure 3: compare_price with no comparable items
result = compare_price({"category": "unicorn_xyz", "price": 99}, load_listings())
# → {"assessment": "unknown", "comparable_count": 0, ...}
```

From running the full agent (`python agent.py`):

```
=== No-results path ===
Error message: No listings found for 'designer ballgown' in size XXS under $5,
even after loosening the filters. Try broader keywords, a different size, or a
higher price ceiling.
Retry attempted: True
```

---

## Spec Reflection

**One way the spec helped:** The error handling table in `planning.md` forced me to think about each tool's failure mode before writing any code. Without it, I might have written `suggest_outfit` that just raised a `ValueError` on an empty wardrobe — specifying "returns general styling advice" before implementing made the right behavior obvious. The table also made it clear that `create_fit_card` should return a string on failure, not raise — which is a non-obvious default.

**One divergence from the spec:** The spec described query parsing as "use regex, string splitting, or ask the LLM." I chose LLM-based parsing (Groq JSON extraction) because thrift queries are highly variable in natural language — "something cozy in XL under 40 bucks" doesn't parse cleanly with regex. The tradeoff is that parsing adds one extra LLM call per query. To mitigate this, the parser uses `temperature=0.0` (deterministic, fast) and has a regex fallback if the LLM call fails, so it never blocks the rest of the pipeline.

---

## AI Usage

### Instance 1: Implementing `search_listings`

I directed Claude to implement `search_listings` in `tools.py` using the Tool 1 spec block from `planning.md` — specifically: the three input parameters (description, size, max_price), the scoring approach (keyword overlap across title + description + style_tags + category + colors + brand), the size-matching rule (case-insensitive substring, so "M" matches "S/M"), and the requirement to return `[]` rather than raise on no results.

What I reviewed and revised: The generated code initially only searched `title` and `style_tags` for keyword matches, missing `description`, `colors`, and `brand`. I revised it to include all relevant fields in the searchable text blob. I also verified the case-insensitive size matching handled the "S/M", "M/L", and "XL (oversized)" size strings in the actual dataset before accepting it.

### Instance 2: Implementing the planning loop in `agent.py`

I directed Claude to implement `run_agent()` using the Architecture diagram and the Planning Loop + State Management sections from `planning.md`. I specifically asked it to implement the retry logic (drop size, raise max_price by 50% when search returns empty) and to store a `retry_note` in the session that could be surfaced to the user.

What I reviewed and revised: The initial implementation didn't distinguish between "empty because filters were too tight" and "empty because no filters were applied" — it retried unconditionally. I revised it to only retry when at least one filter (size or max_price) was present, since there's nothing to loosen if no filters were applied. I also verified that `suggest_outfit` and `create_fit_card` were never called when the search returned empty after retry — the early return was confirmed by running the no-results test case in the CLI block at the bottom of `agent.py`.

---

## File Structure

```
ai201-project2-fitfindr-starter/
├── data/
│   ├── listings.json          # 40 mock secondhand listings
│   └── wardrobe_schema.json   # Wardrobe format + example wardrobe
├── utils/
│   └── data_loader.py         # load_listings(), get_example_wardrobe(), get_empty_wardrobe()
├── tests/
│   └── test_tools.py          # pytest tests for all failure modes
├── tools.py                   # search_listings, suggest_outfit, create_fit_card, compare_price
├── agent.py                   # run_agent() planning loop
├── app.py                     # Gradio interface
├── planning.md                # Design spec (filled in before implementation)
├── requirements.txt
└── .env                       # GROQ_API_KEY (not committed)
```
