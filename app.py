"""
app.py

Gradio interface for FitFindr. The layout and wiring are already set up —
handle_query() calls run_agent() and maps the session results to the three
output panels.

Run with:
    python app.py

Then open the localhost URL shown in your terminal (usually http://localhost:7860,
but check your terminal — the port may differ).
"""

import gradio as gr

from agent import run_agent
from utils.data_loader import get_example_wardrobe, get_empty_wardrobe


# ── query handler ─────────────────────────────────────────────────────────────

def handle_query(user_query: str, wardrobe_choice: str) -> tuple[str, str, str]:
    """
    Called by Gradio when the user submits a query.

    Args:
        user_query:     The text the user typed into the search box.
        wardrobe_choice: Either "Example wardrobe" or "Empty wardrobe (new user)".

    Returns:
        A tuple of three strings:
            (listing_text, outfit_suggestion, fit_card)
        Each string maps to one of the three output panels in the UI.
    """
    # Step 1: Guard against empty query
    if not user_query or not user_query.strip():
        return "Please enter a search query to get started.", "", ""

    # Step 2: Select wardrobe based on user choice
    if wardrobe_choice == "Example wardrobe":
        wardrobe = get_example_wardrobe()
    else:
        wardrobe = get_empty_wardrobe()

    # Step 3: Run the agent
    session = run_agent(user_query, wardrobe)

    # Step 4: If error, return error in panel 1, empty strings for panels 2 & 3
    if session["error"]:
        return session["error"], "", ""

    # Step 5: Format the selected item into readable listing text
    item = session["selected_item"]
    brand_str = f" by {item['brand']}" if item.get("brand") else ""
    colors_str = ", ".join(item.get("colors", []))

    listing_text = (
        f"{item['title']}{brand_str}\n"
        f"${item['price']:.2f}  ·  {item['platform']}  ·  {item['condition']} condition\n"
        f"Size: {item['size']}  ·  Colors: {colors_str}\n\n"
        f"{item['description']}"
    )

    # Add retry note if search was loosened
    if session.get("retry_note"):
        listing_text = f"⚠️ {session['retry_note']}\n\n" + listing_text

    # Add price assessment if available (stretch)
    if session.get("price_assessment"):
        pa = session["price_assessment"]
        if pa["assessment"] != "unknown":
            emoji = {"below average": "🟢", "fair": "🟡", "above average": "🔴"}.get(
                pa["assessment"], "💰"
            )
            listing_text += (
                f"\n\n{emoji} Price check: {pa['verdict']}"
            )

    outfit_text = session["outfit_suggestion"] or ""
    fitcard_text = session["fit_card"] or ""

    return listing_text, outfit_text, fitcard_text


# ── interface ─────────────────────────────────────────────────────────────────

EXAMPLE_QUERIES = [
    "vintage graphic tee under $30",
    "90s track jacket in size M",
    "flowy midi skirt under $40",
    "black combat boots size 8",
    "designer ballgown size XXS under $5",   # deliberate no-results test
]

def build_interface():
    with gr.Blocks(title="FitFindr") as demo:
        gr.Markdown("""
# FitFindr 🛍️
Find secondhand pieces and get outfit ideas based on your wardrobe.
Describe what you're looking for — include size and price if you want to filter.
        """)

        with gr.Row():
            query_input = gr.Textbox(
                label="What are you looking for?",
                placeholder="e.g. vintage graphic tee under $30, size M",
                lines=2,
                scale=3,
            )
            wardrobe_choice = gr.Radio(
                choices=["Example wardrobe", "Empty wardrobe (new user)"],
                value="Example wardrobe",
                label="Wardrobe",
                scale=1,
            )

        submit_btn = gr.Button("Find it", variant="primary")

        with gr.Row():
            listing_output = gr.Textbox(
                label="🛍️ Top listing found",
                lines=8,
                interactive=False,
            )
            outfit_output = gr.Textbox(
                label="👗 Outfit idea",
                lines=8,
                interactive=False,
            )
            fitcard_output = gr.Textbox(
                label="✨ Your fit card",
                lines=8,
                interactive=False,
            )

        gr.Examples(
            examples=[[q, "Example wardrobe"] for q in EXAMPLE_QUERIES],
            inputs=[query_input, wardrobe_choice],
            label="Try these queries",
        )

        submit_btn.click(
            fn=handle_query,
            inputs=[query_input, wardrobe_choice],
            outputs=[listing_output, outfit_output, fitcard_output],
        )
        query_input.submit(
            fn=handle_query,
            inputs=[query_input, wardrobe_choice],
            outputs=[listing_output, outfit_output, fitcard_output],
        )

    return demo


if __name__ == "__main__":
    demo = build_interface()
    demo.launch()
