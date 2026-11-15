import time
from google import genai
import requests
import streamlit as st

st.set_page_config(
    page_title="Retail Price Intelligence Agent",
    page_icon="🏷️",
    layout="centered",
)

st.title("🏷️ Real-Time Price Comparison Agent")
st.caption("Powered by Live Google Search India + Gemini 3.5 Flash-Lite")

gemini_key = (
    st.secrets.get("GEMINI_API_KEY")
    if "GEMINI_API_KEY" in st.secrets
    else st.sidebar.text_input("Gemini API Key", type="password")
)
serper_key = (
    st.secrets.get("SERPER_API_KEY")
    if "SERPER_API_KEY" in st.secrets
    else st.sidebar.text_input("Serper API Key", type="password")
)


# Caches results for 24 hours (86400 seconds) so repeat searches use 0 Serper credits
@st.cache_data(ttl=86400, show_spinner=False)
def fetch_live_retail_data(product_name, api_key):
  headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}
  # Single 1-credit search call targeting Indian retail product pages and prices
  res = requests.post(
      "https://google.serper.dev/search",
      headers=headers,
      json={
          "q": (
              f"{product_name} price in India ₹ (site:amazon.in OR"
              " site:flipkart.com OR site:croma.com OR"
              " site:reliancedigital.in)"
          ),
          "gl": "in",
          "hl": "en",
          "num": 10,
      },
      timeout=10,
  ).json()

  records = []
  for item in res.get("organic", []):
    price_str = f" | Price tag: {item.get('price')}" if item.get("price") else ""
    records.append(
        f"Title: {item.get('title')}{price_str} | Snippet:"
        f" {item.get('snippet')} | Direct URL: {item.get('link')}"
    )
  return "\n".join(records)


product = st.text_input(
    "Enter product name (e.g., PlayStation 5 Slim, Xbox Series X, Sony"
    " WH-1000XM5):"
)

if st.button("Find Lowest Price", type="primary"):
  if not gemini_key or not serper_key:
    st.error("Please ensure both GEMINI_API_KEY and SERPER_API_KEY are set.")
  elif not product.strip():
    st.warning("Please enter a product name.")
  else:
    with st.spinner("Scanning verified Indian retail listings..."):
      try:
        search_context = fetch_live_retail_data(
            product.strip().lower(), serper_key
        )

        if not search_context.strip():
          st.warning(
              "No live listings found. Try a slightly more specific product"
              " name."
          )
        else:
          client = genai.Client(api_key=gemini_key)

          prompt = f"""
                    You are a strict e-commerce price verification agent for India.
                    Below is real-time data from Indian retail product pages for: "{product}".

                    VERIFIED LIVE DATA:
                    {search_context}

                    STRICT AUDIT RULES:
                    1. ZERO HALLUCINATION: Only report prices (in ₹ / Rs.) and URLs explicitly found in the VERIFIED LIVE DATA above. Do not invent prices.
                    2. FILTER OUT ACCESSORIES: Ignore cables, cases, controllers, or games unless specifically requested.
                    3. DIRECT LINKS ONLY: Use ONLY the exact 'Direct URL' from the raw data above.
                    4. Output a clean Markdown table:
                       | Exact Product Title | Retailer | Verified Live Price (₹) | Direct Product Link |
                       Format the link as [View Product Page](exact_url_from_data).
                    5. Conclude with a brief 'Verified Lowest Price' summary naming the cheapest retailer and exact Rupee difference.
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
            with st.expander("✅ Audit Trail: View Raw Retailer Data"):
              st.text(search_context)
          else:
            st.error("Gemini servers are temporarily busy. Please try again.")

      except Exception as e:
        st.error(f"Error fetching live data: {e}")
