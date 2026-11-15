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
st.caption("Powered by Live Google Shopping India Feed + Gemini 3.5 Flash-Lite")

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
    with st.spinner(
        "Pulling verified listings from Google Shopping India & Retailers..."
    ):
      try:
        headers = {
            "X-API-KEY": serper_key,
            "Content-Type": "application/json",
        }

        # 1. Fetch live Google Shopping India listings (verified prices & direct merchant links)
        shop_res = requests.post(
            "https://google.serper.dev/shopping",
            headers=headers,
            json={"q": product, "gl": "in", "hl": "en", "num": 10},
            timeout=10,
        ).json()

        # 2. Fetch direct product pages from Amazon.in, Flipkart, Croma, Reliance Digital
        web_res = requests.post(
            "https://google.serper.dev/search",
            headers=headers,
            json={
                "q": (
                    f"{product} buy online India (site:amazon.in OR"
                    " site:flipkart.com OR site:croma.com OR"
                    " site:reliancedigital.in)"
                ),
                "gl": "in",
                "hl": "en",
                "num": 10,
            },
            timeout=10,
        ).json()

        raw_records = []

        for item in shop_res.get("shopping", []):
          raw_records.append(
              f"[GOOGLE SHOPPING] Title: {item.get('title')} | Store:"
              f" {item.get('source')} | Exact Price: {item.get('price')} |"
              f" Direct URL: {item.get('link')}"
          )

        for item in web_res.get("organic", []):
          price_info = item.get("price", "") or item.get("snippet", "")
          raw_records.append(
              f"[DIRECT RETAILER PAGE] Title: {item.get('title')} | Snippet/Price:"
              f" {price_info} | Direct Product URL: {item.get('link')}"
          )

        search_context = "\n".join(raw_records)

        if not search_context.strip():
          st.error(
              "No live listings returned from Google India. Check your Serper"
              " API key or product spelling."
          )
        else:
          client = genai.Client(api_key=gemini_key)

          prompt = f"""
                    You are a strict, audit-grade e-commerce price verification agent for India.
                    Below is real-time data pulled directly from Google Shopping India and Indian retail product pages for: "{product}".

                    VERIFIED LIVE DATA:
                    {search_context}

                    STRICT AUDIT RULES (NO EXCEPTIONS):
                    1. ZERO HALLUCINATION: You must ONLY report prices and URLs that explicitly appear in the VERIFIED LIVE DATA above. Never guess, estimate, or pull prices from your training memory.
                    2. FILTER OUT ACCESSORIES: Ignore cables, controllers, skins, bags, or games unless the user specifically asked for them. Only include the main product/console.
                    3. DIRECT LINKS ONLY: In the 'Direct Product Link' column, use ONLY the exact 'Direct URL' or 'Direct Product URL' from the raw data above. NEVER construct generic search links.
                    4. Output a clean Markdown table:
                       | Exact Product Title | Retailer | Verified Live Price (₹) | Direct Product Link |
                       Format the link as [View Product Page](exact_url_from_data).
                    5. Conclude with a brief 'Verified Lowest Price' summary stating the cheapest retailer and exact Rupee difference based strictly on the table.
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
            with st.expander(
                "✅ Audit Trail: View Raw Google Shopping & Retailer Data"
            ):
              st.text(search_context)
          else:
            st.error("Gemini servers are temporarily busy. Please try again.")

      except Exception as e:
        st.error(f"Error fetching live data: {e}")
