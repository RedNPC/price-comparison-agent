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
    "Powered by Gemini 3.5 Flash-Lite + Targeted Retail Search (Zero-Cost Free"
    " Tier)"
)

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
    with st.spinner(
        "Agent is scanning Amazon, Flipkart, and retail price indexes..."
    ):
      try:
        # Step 1: Run 3 focused searches targeting exact rupee prices
        search_results = []
        queries = [
            f'"{product}" "₹" site:amazon.in',
            f'"{product}" "₹" site:flipkart.com',
            f'"{product}" price India "₹" Croma OR Reliance',
        ]

        with DDGS() as ddgs:
          for q in queries:
            try:
              results = list(ddgs.text(q, region="in-en", max_results=4))
              search_results.extend(results)
            except Exception:
              continue

        search_context = "\n\n".join([
            f"Title: {r.get('title')}\nSnippet: {r.get('body')}\nURL:"
            f" {r.get('href')}"
            for r in search_results
        ])

        if not search_context.strip():
          st.warning("No pricing data found. Please refine the product name.")
        else:
          client = genai.Client(api_key=api_key)

          prompt = f"""
                    You are a procurement price analyst.
                    The user wants to find the best purchase price in India for: "{product}".

                    RAW RETAIL SEARCH DATA:
                    {search_context}

                    MANDATORY INSTRUCTIONS:
                    1. Scrutinize the snippets for exact numerical prices in INR (₹ or Rs.). NEVER output "Check Site" as the price if any numeric figure is present in the text.
                    2. If you see specific prices (e.g., ₹44,990, ₹49,990, ₹54,990, ₹64,990, ₹69,990), match each price to its retailer and exact model variant (e.g., Slim Disc vs. Slim Digital).
                    3. If an exact platform's live price is missing from the snippets, output the standard Indian market price or last recorded listing with an asterisk (*).
                    4. Output a clean Markdown comparison table:
                       | Product / Variant | Retailer | Listed Price (₹) | Status / Stock | Direct Link |
                    5. Provide a direct verdict: Which retailer offers the lowest listed price right now, and what is the exact cash variance/saving compared to other stores?
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
          else:
            st.error("Service busy. Please retry in a few moments.")

      except Exception as e:
        st.error(f"Error fetching prices: {e}")
