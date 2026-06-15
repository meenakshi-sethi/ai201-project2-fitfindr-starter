# FitFindr — planning.md

> Complete this document before writing any implementation code.
> Your spec and agent diagram are what you'll use to direct AI tools (Claude, Copilot, etc.) to generate your implementation — the more specific they are, the more useful the generated code will be.
> Your planning.md will be reviewed as part of your submission.
> Update it before starting any stretch features.

---

## Tools

List every tool your agent will use. For each tool, fill in all four fields.
You must have at least 3 tools. The three required tools are listed — add any additional tools below them.

### Tool 1: search_listings

**What it does:**
Searches the mock listings dataset for secondhand items that match a user's natural-language description, with optional filters for size and maximum price. Returns a relevance-ranked list of matching listing dicts.

**Input parameters:**
- `description` (str): Keywords describing what the user is looking for (e.g., "vintage graphic tee"). Used for keyword scoring across title, description, style_tags, and category fields.
- `size` (str | None): Size string to filter by, or None to skip size filtering. Matching is case-insensitive substring match so "M" matches "S/M" and "M/L".
- `max_price` (float | None): Maximum price ceiling (inclusive), or None to skip price filtering.

**What it returns:**
A list of listing dicts sorted by relevance score (best match first). Each dict contains: `id` (str), `title` (str), `description` (str), `category` (str), `style_tags` (list[str]), `size` (str), `condition` (str), `price` (float), `colors` (list[str]), `brand` (str | None), `platform` (str). Returns an empty list `[]` if nothing matches — never raises an exception.

**What happens if it fails or returns nothing:**
If the list is empty, the agent first retries with loosened constraints: size filter is dropped and max_price is increased by 50% (or removed if it was None). The agent informs the user what was adjusted ("I loosened the size filter and raised your price ceiling to $X — here's what I found."). If the retry also returns empty, the agent sets `session["error"]` to a helpful message such as "No listings found for 'designer ballgown'. Try broader keywords, a different size, or raise your price ceiling above $5." and returns early without calling suggest_outfit or create_fit_card.

---

### Tool 2: suggest_outfit

**What it does:**
Given a specific thrifted item the user is considering and their existing wardrobe, calls the Groq LLM to suggest 1–2 complete outfit combinations. When the wardrobe is empty (new user), provides general styling advice instead of wardrobe-specific combinations.

**Input parameters:**
- `new_item` (dict): A listing dict representing the item the user is considering buying (the top result from search_listings). Contains title, description, style_tags, colors, category, etc.
- `wardrobe` (dict): A wardrobe dict with an `'items'` key containing a list of wardrobe item dicts. Each wardrobe item has: name, category, colors (list), style (str), and notes (str). May be empty — handle this gracefully.

**What it returns:**
A non-empty string with outfit suggestions. If the wardrobe has items, the string names specific pieces from the wardrobe and explains how to combine them with the new item. If the wardrobe is empty, the string provides general styling advice: what kinds of pieces complement this item, what aesthetic/vibe it fits, and how to build an outfit around it.

**What happens if it fails or returns nothing:**
If `wardrobe['items']` is empty, the tool does NOT fail — it switches to a general styling prompt instead of crashing. If the Groq API call itself fails (network error, rate limit), the tool returns a fallback string: "Unable to generate outfit suggestion at this time. This item would pair well with basics like a plain white tee, straight-leg jeans, or neutral sneakers depending on its style." The agent continues to create_fit_card using this fallback string.

---

### Tool 3: create_fit_card

**What it does:**
Generates a short, shareable 2–4 sentence outfit caption for the thrifted find — the kind of casual, authentic text someone would caption an Instagram or TikTok OOTD post with. Calls the Groq LLM with a higher temperature for creative variation.

**Input parameters:**
- `outfit` (str): The outfit suggestion string returned by suggest_outfit. This is the primary content the caption is built around.
- `new_item` (dict): The listing dict for the thrifted item. Used to extract title, price, and platform to mention naturally in the caption.

**What it returns:**
A 2–4 sentence string that: mentions the item name, price, and platform once each; feels casual and authentic (not like a product description); captures the outfit's vibe in specific terms; and sounds different across different inputs (achieved via temperature=0.9 in the LLM call).

**What happens if it fails or returns nothing:**
If `outfit` is empty or whitespace-only, the tool immediately returns a descriptive error string without calling the LLM: "Unable to create fit card: the outfit suggestion is missing. Please search for an item first so I have styling context to work with." This is a string return, not a Python exception. If the Groq API call fails, the tool returns a minimal fallback caption using only the item details: f"just thrifted this {new_item['title']} off {new_item['platform']} for ${new_item['price']} — tell me how to style it 👀"

---

### Additional Tools

### Tool 4: compare_price (stretch)

**What it does:**
Given a specific listing item, evaluates whether its price is fair by comparing it against similar listings in the same category. Returns a price assessment with reasoning.

**Input parameters:**
- `item` (dict): The listing dict to evaluate (same format as search_listings output).
- `all_listings` (list[dict]): The full listings dataset to compare against. Loaded via load_listings().

**What it returns:**
A dict with four keys: `assessment` (str — "below average", "fair", or "above average"), `comparable_avg` (float — mean price of comparable items), `comparable_count` (int — number of items used for comparison), and `verdict` (str — a one-sentence human-readable verdict like "This $22 tee is below average for tops in this dataset, where similar items average $31.").

**What happens if it fails or returns nothing:**
If there are no comparable items (comparable_count == 0), returns `{"assessment": "unknown", "comparable_avg": 0.0, "comparable_count": 0, "verdict": "Not enough comparable listings to assess this price."}`. Never raises an exception.

---

## Planning Loop

**How does your agent decide which tool to call next?**

The agent follows a linear-with-branching planning loop. Here is the specific conditional logic at each step:

1. **Parse query**: The agent calls the Groq LLM to extract `description`, `size`, and `max_price` from the natural language query. If parsing returns an empty description, the agent falls back to using the full query as the description. This step always produces usable output — it never terminates early.

2. **Call search_listings(description, size, max_price)**:
   - If results is non-empty: store `session["search_results"] = results`, set `session["selected_item"] = results[0]`, and proceed to step 3.
   - If results is empty AND a size or max_price was specified (meaning loosening is possible): set `session["retry_attempted"] = True`, retry with `size=None` and `max_price *= 1.5` (or None if no max_price was given), inform the user what was adjusted. If retry produces results, store and proceed. If retry also empty: set `session["error"]` to a specific message describing what was tried and what the user can change, then **return the session immediately** — do NOT call suggest_outfit or create_fit_card with empty input.
   - If results is empty AND no filters were applied (size=None, max_price=None): set `session["error"]` immediately with a message suggesting different keywords, then return early.

3. **Call compare_price(selected_item, load_listings())** (stretch): Always runs if step 2 succeeded. Stores `session["price_assessment"]`. Never causes early termination — failure returns a "unknown" assessment dict.

4. **Call suggest_outfit(selected_item, wardrobe)**: Always called after a successful search step. The wardrobe passed in is the same object the agent received at initialization (from `session["wardrobe"]`). Result is stored in `session["outfit_suggestion"]`. If suggest_outfit returns a fallback string (Groq error), the agent still proceeds to step 5.

5. **Call create_fit_card(outfit_suggestion, selected_item)**: Called with `session["outfit_suggestion"]` and `session["selected_item"]`. These are always non-None at this point because the agent would have returned early in step 2 if search failed, and suggest_outfit always returns a non-empty string. Result stored in `session["fit_card"]`.

6. **Return session**: The completed session dict is returned with all output fields populated.

**What makes this loop adaptive (not unconditional):** The key branch is at step 2. If search returns no results, the agent does NOT call suggest_outfit or create_fit_card — it returns an error. The user sees a specific, actionable error message rather than an empty outfit or empty fit card. Additionally, the retry logic in step 2 means the agent first tries to self-correct before giving up.

---

## State Management

**How does information from one tool get passed to the next?**

All state lives in a single `session` dict initialized at the start of each interaction. Here is what is stored, when it is set, and how it flows:

| Field | Set when | Used by |
|-------|----------|---------|
| `session["query"]` | On initialization | LLM query parser |
| `session["parsed"]` | After LLM query parse | search_listings call |
| `session["search_results"]` | After search_listings returns | Display, selected_item selection |
| `session["selected_item"]` | After search_listings — `results[0]` | suggest_outfit, create_fit_card, compare_price |
| `session["wardrobe"]` | On initialization (passed in by caller) | suggest_outfit |
| `session["price_assessment"]` | After compare_price | app.py display only |
| `session["outfit_suggestion"]` | After suggest_outfit | create_fit_card |
| `session["fit_card"]` | After create_fit_card | app.py display only |
| `session["error"]` | On early termination | app.py: routes to error display |
| `session["retry_attempted"]` | If search retry fires | README / transparency |

The key state handoffs are:
- `session["selected_item"]` is the exact same dict object passed into both `suggest_outfit` and `create_fit_card` — no re-entry, no re-fetch.
- `session["outfit_suggestion"]` is the exact string from `suggest_outfit` passed directly into `create_fit_card` — no re-entry.
- The `wardrobe` is stored in the session at initialization and accessed in step 4, so it also never requires re-entry.

---

## Error Handling

For each tool, describe the specific failure mode you're handling and what the agent does in response.

| Tool | Failure mode | Agent response |
|------|-------------|----------------|
| search_listings | No listings match the query (empty list returned) | Agent first retries with loosened constraints (drop size, raise max_price 50%). If still empty: sets `session["error"]` = "No listings found for '{description}' even after loosening filters. Try different keywords, a larger size range, or raise your budget above ${max_price}." Returns early — does NOT call suggest_outfit. |
| suggest_outfit | Wardrobe is empty (wardrobe['items'] == []) | Tool switches to a general styling prompt: asks the LLM what kinds of pieces pair well with this item and what aesthetic it fits, without referencing any specific wardrobe items. Always returns a non-empty string. |
| suggest_outfit | Groq API call fails (exception) | Returns fallback string: "Unable to generate outfit suggestions right now. This item would pair well with basics like a plain tee, jeans, or neutral sneakers depending on its style." Agent continues to create_fit_card with this fallback. |
| create_fit_card | outfit parameter is empty or whitespace | Returns immediately with descriptive error string: "Unable to create fit card: outfit suggestion is missing. Please search for an item first so I have styling context to work with." No LLM call made. |
| create_fit_card | Groq API call fails (exception) | Returns minimal fallback caption using only item dict fields: f"just thrifted this {item['title']} off {item['platform']} for ${item['price']} — tell me how to style it 👀" |

---

## Architecture

```
User query (natural language)
     │
     ▼
Planning Loop (run_agent in agent.py)
     │
     ├─ Step 1: Parse query via Groq LLM
     │         │
     │         ▼  session["parsed"] = {description, size, max_price}
     │
     ├─ Step 2: search_listings(description, size, max_price)
     │         │
     │         ├── results = [] AND filters exist
     │         │       │
     │         │       ▼  [RETRY] loosen constraints (drop size, raise max_price)
     │         │       │
     │         │       ├── retry results = [] ──► session["error"] = "No listings found..." → RETURN EARLY
     │         │       │
     │         │       └── retry results = [item, ...] ──► session["search_results"], session["retry_attempted"] = True
     │         │
     │         ├── results = [] AND no filters ──► session["error"] = "No listings found..." → RETURN EARLY
     │         │
     │         └── results = [item, ...] ──► session["search_results"] = results
     │                                       session["selected_item"] = results[0]
     │
     ├─ Step 3: compare_price(selected_item, all_listings)  [stretch]
     │         │
     │         ▼  session["price_assessment"] = {assessment, avg, count, verdict}
     │         (never causes early termination)
     │
     ├─ Step 4: suggest_outfit(selected_item, wardrobe)
     │         │
     │         ├── wardrobe empty ──► general styling advice from LLM
     │         ├── wardrobe non-empty ──► specific outfit combos from LLM
     │         └── Groq API error ──► fallback string
     │         │
     │         ▼  session["outfit_suggestion"] = "..."
     │
     ├─ Step 5: create_fit_card(outfit_suggestion, selected_item)
     │         │
     │         ├── outfit empty ──► descriptive error string (no LLM call)
     │         └── Groq API error ──► minimal fallback caption
     │         │
     │         ▼  session["fit_card"] = "..."
     │
     └─ Step 6: return session
                    │
                    ▼
              app.py: handle_query()
                    │
                    ├── session["error"] set → error panel (panel 1), empty panels 2 & 3
                    └── success → panel 1: listing details + price check
                                  panel 2: outfit suggestion
                                  panel 3: fit card caption
```

---

## AI Tool Plan

**Milestone 3 — Individual tool implementations:**

For `search_listings`, I will give Claude the Tool 1 spec block from this planning.md (inputs, return value, filtering logic, scoring approach, failure mode) and ask it to implement the function in `tools.py` using `load_listings()` from `utils/data_loader.py`. Before running, I will verify: (1) it filters by both price and size, (2) size matching is case-insensitive substring, (3) scoring counts keyword matches across title + description + style_tags + category, (4) items with score 0 are dropped, (5) empty list is returned (not an exception) when nothing matches. Then test with 3 queries: one that should return results, one that should return empty, and one that tests the price filter.

For `suggest_outfit`, I will give Claude the Tool 2 spec block (both empty-wardrobe and non-empty paths, the fallback for Groq errors, and the wardrobe dict structure from data/wardrobe_schema.json). I will ask it to implement the function making one Groq API call with llama-3.3-70b-versatile at temperature=0.7. Before running, I will check: (1) it checks `wardrobe['items']` for empty, (2) the two prompt branches are distinct, (3) the try/except around the Groq call returns the fallback string rather than re-raising. Test manually with get_empty_wardrobe() and get_example_wardrobe().

For `create_fit_card`, I will give Claude the Tool 3 spec block (the empty-outfit guard, the caption style guidelines, and the fallback) and ask it to implement the function at temperature=0.9. Before running, I will check: (1) the empty-outfit guard returns a string (not raises), (2) the prompt instructs casual tone and specific vibe, (3) temperature is 0.9. Run the same input 3 times and verify outputs differ.

**Milestone 4 — Planning loop and state management:**

I will give Claude the full Architecture diagram and the Planning Loop + State Management sections from this planning.md, plus the existing `_new_session()` function, and ask it to implement `run_agent()` in `agent.py`. Before running, I will verify: (1) it calls `_new_session()`, (2) the Groq query-parsing step stores results in `session["parsed"]`, (3) there is an explicit check for empty search results that returns early before calling suggest_outfit, (4) the retry logic fires when results are empty and filters were applied, (5) state flows through the session dict (no hardcoded values, no re-prompting user). Test both the happy-path and the no-results path using the CLI test block at the bottom of agent.py.

---

## A Complete Interaction (Step by Step)

**Example user query:** "I'm looking for a vintage graphic tee under $30. I mostly wear baggy jeans and chunky sneakers. What's out there and how would I style it?"

**Step 1: Query parsing**
The agent passes the query to the Groq LLM with a structured extraction prompt. The LLM returns JSON: `{"description": "vintage graphic tee", "size": null, "max_price": 30.0}`. This is stored in `session["parsed"]`. The wardrobe context ("baggy jeans and chunky sneakers") is not used here — it comes from the wardrobe dict passed into run_agent().

**Step 2: Search**
`search_listings("vintage graphic tee", size=None, max_price=30.0)` is called. The function loads all 40 listings, filters to items priced ≤ $30, then scores each by counting how many of the words ["vintage", "graphic", "tee"] appear in each listing's title + description + style_tags + category. Items with score 0 are dropped. Remaining items are sorted highest-score-first. The function returns 3–4 matching listings. The top result is: `{"title": "Graphic Tee — 2003 Tour Bootleg Style", "price": 24.0, "platform": "depop", "condition": "good", ...}`. This is stored in `session["search_results"]` and `session["selected_item"]`.

**Step 3: Price comparison (stretch)**
`compare_price(selected_item, load_listings())` filters all listings by category="tops", computes an average price (~$28), and returns `{"assessment": "fair", "comparable_avg": 28.0, "comparable_count": 12, "verdict": "This $24 tee is fair for tops in this dataset, where similar items average $28."}`. Stored in `session["price_assessment"]`.

**Step 4: Outfit suggestion**
`suggest_outfit(selected_item, wardrobe)` is called with the graphic tee listing and the example wardrobe (10 items including wide-leg jeans, chunky sneakers). Since the wardrobe is non-empty, the agent formats the wardrobe items into a readable list and asks the Groq LLM for specific outfit combinations. The LLM returns: "Pair this faded graphic tee with your wide-leg jeans and platform Docs for a classic 90s grunge look. Roll the sleeves once and tuck the front corner slightly for shape. For a more streetwear take, try it with your track pants and clean white sneakers — add an unbuttoned flannel over the top." Stored in `session["outfit_suggestion"]`.

**Step 5: Fit card**
`create_fit_card(outfit_suggestion, selected_item)` is called with the outfit string and the graphic tee dict. The LLM (at temperature=0.9) generates: "thrifted this faded bootleg tee off depop for $24 and honestly it was made for my wide-legs 🖤 grunge era is never leaving. full look dropping soon". Stored in `session["fit_card"]`.

**Step 6: Return**
The session is returned to `handle_query()` in app.py, which formats the listing details into panel 1 (title, price, platform, condition, description, price check verdict), passes `session["outfit_suggestion"]` to panel 2, and `session["fit_card"]` to panel 3. The user sees all three panels populated.

**Final output to user:**
- Panel 1 — Top listing: "Graphic Tee — 2003 Tour Bootleg Style / $24.00 · depop · good condition / Size: L / Vintage-style bootleg tee with faded graphic... / 💰 Price check: This $24 tee is fair for tops, where similar items average $28."
- Panel 2 — Outfit idea: "Pair this faded graphic tee with your wide-leg jeans and platform Docs for a classic 90s grunge look..."
- Panel 3 — Fit card: "thrifted this faded bootleg tee off depop for $24 and honestly it was made for my wide-legs 🖤 grunge era is never leaving..."

**Error path (alternate):** If the user had searched "designer ballgown size XXS under $5", search_listings returns []. Since size and max_price filters were applied, the agent retries with size=None and max_price=$7.50. The retry also returns []. The agent sets `session["error"]` = "No listings found for 'designer ballgown' even after loosening filters. Try different keywords or raise your budget above $7.50." suggest_outfit and create_fit_card are never called. Panel 1 shows the error; panels 2 and 3 are empty.
