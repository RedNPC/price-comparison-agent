import time
from ddgs import DDGS
from google import genai
import streamlit as st

st.set_page_config(
    page_title="Retail Price Intelligence Agent",
    page_icon="🏷️",
    layout="centered",
)

st.title("🏷️ Real-Time Price Comparison Agent")
st.caption("Powered by Gemini 3.5 Flash-Lite + Retail Web Search")

api_key = (
    st.secrets.get("GEMINI_API_KEY")
    if "GEMINI_API_KEY" in st.secrets
    else st.sidebar.text_input("Enter Gemini API Key", type="password")
)

product = st.text_input(
    "Enter product name (e.g., PlayStation 5, Xbox Series X, Sony WH-1000XM5):"
)

if st.button("Find Lowest Price", type="primary"):
  if not api_key:
    st.error("Please provide a Gemini API Key to run the agent.")
  elif not product.strip():
    st.warning("Please enter a product name.")
  else:
    with st.spinner("Scanning Indian retail listings and analyzing prices..."):
      try:
        search_context = ""
        try:
          query = (
              f"{product} price in India Rs Buy online Flipkart Amazon Croma"
              " Reliance Digital"
          )
          with DDGS() as ddgs:
            results = list(ddgs.text(query, region="in-en", max_results=10))
          if results:
            search_context = "\n\n".join([
                f"Source: {r.get('title')}\nDetails: {r.get('body')}\nURL:"
                f" {r.get('href')}"
                for r in results
            ])
        except Exception:
          search_context = ""

        client = genai.Client(api_key=api_key)

        prompt = f"""
                You are an Indian e-commerce procurement and price comparison agent.
                The user is searching for the lowest current price in India (in INR / ₹) for: "{product}".

                LIVE WEB SEARCH SNIPPETS:
                {search_context if search_context else "Live scraper throttled; use your latest indexed Indian retail pricing data."}

                MANDATORY INSTRUCTIONS:
                1. Identify the main variants if the query is broad (e.g., for PlayStation 5, separate PS5 Slim Digital Edition vs. PS5 Slim Disc Standard Edition).
                2. Extract the exact numerical price in INR (₹) for Amazon.in, Flipkart, Croma, and other Indian retailers from the snippets.
                3. NEVER write "Check Site" in the price column. Always provide the numeric price in ₹ (if a store's live snippet only shows a category link, provide its current standard Indian retail listing price and mark it with an asterisk *).
                4. Output a clean Markdown comparison table with 5 columns:
                   | Model / Variant | Retailer | Listed Price (₹) | Availability | Store Link |
                5. For the 'Store Link' column, format every entry as a clickable Markdown link like [Buy on Amazon](URL):
                   - If a matching URL is present in the LIVE WEB SEARCH SNIPPETS above, use that exact URL.
                   - If no exact URL is in the snippets for that store, construct a working search link by replacing spaces in the model name with '+' using these exact templates:
                     * Amazon.in: https://www.amazon.in/s?k=MODEL+NAME
                     * Flipkart: https://www.flipkart.com/search?q=MODEL+NAME
                     * Croma: https://www.croma.com/searchB?q=MODEL+NAME
                     * Reliance Digital: https://www.reliancedigital.in/search?q=MODEL+NAME
                   - Never invent fake product URLs.
                6. Finish with a bold 2-sentence 'Bottom-Line Verdict' naming the cheapest place to buy right now and the exact Rupee savings.
                """

        models_to_try = ["gemini-3.5-flash-lite", "gemini-3.8-flash"]
        response = None

        for model_name in models_to_try:
          try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
            )
            if response and response.text:
              break
          except Exception as model_err:
            if "503" in str(model_err) or "UNAVAILABLE" in str(model_err):
              time.sleep(1)
              continue
            else:
              raise model_err

        if response and response.text:
          st.markdown(response.text)
          if search_context:
            with st.expander("View Raw Search Snippets Scanned by Agent"):
              st.text(search_context)
        else:
          st.error("Google servers are temporarily busy. Please click again.")

      except Exception as e:
        st.error(f"Error fetching prices: {e}")
