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
st.caption(
    "Powered by Gemini 3.5 Flash-Lite + Live Web Search (Zero-Cost Free Tier)"
)

api_key = (
    st.secrets.get("GEMINI_API_KEY")
    if "GEMINI_API_KEY" in st.secrets
    else st.sidebar.text_input("Enter Gemini API Key", type="password")
)

product = st.text_input(
    "Enter product name (e.g., Xbox Series X 1TB, Sony WH-1000XM5):"
)

if st.button("Find Lowest Price", type="primary"):
  if not api_key:
    st.error("Please provide a Gemini API Key to run the agent.")
  elif not product.strip():
    st.warning("Please enter a product name.")
  else:
    with st.spinner("Agent is querying live web listings..."):
      try:
        # Step 1: Query live search snippets across Indian retailers
        search_query = f"{product} price in India Amazon.in Flipkart Croma"
        with DDGS() as ddgs:
          raw_results = list(
              ddgs.text(search_query, region="in-en", max_results=8)
          )

        search_context = "\n\n".join([
            f"Title: {r.get('title')}\nSnippet: {r.get('body')}\nURL:"
            f" {r.get('href')}"
            for r in raw_results
        ])

        if not search_context.strip():
          st.warning("No search results found. Try a different product name.")
        else:
          client = genai.Client(api_key=api_key)

          prompt = f"""
                    You are a procurement and price intelligence agent.
                    Below are live search results from Indian retail sites for the product: "{product}".

                    LIVE SEARCH RESULTS:
                    {search_context}

                    INSTRUCTIONS:
                    1. Extract the current standard face-value listed price (in INR / ₹) on Amazon.in, Flipkart, and other retailers. Ignore card/bank discounts.
                    2. If the user query is broad (e.g., "PlayStation 5" or "Xbox"), identify the separate variants (e.g., Disc vs Digital Edition) and group them so you do not compare different models.
                    3. Calculate the variance/savings between the highest and lowest price found.
                    4. Output a clean Markdown table:
                       | Variant / Model | Retailer | Listed Price (₹) | In Stock? | Source Link |
                    5. Provide a direct, concise purchase recommendation highlighting the lowest-cost option.
                    """

          # Step 2: Fallback handling across available lightweight models
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
          else:
            st.error(
                "Google servers are experiencing peak congestion. Please try"
                " again in a few moments."
            )

      except Exception as e:
        st.error(f"Error fetching prices: {e}")
