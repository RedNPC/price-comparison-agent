import time
from google import genai
import requests
import streamlit as st

st.set_page_config(
    page_title="Retail Price Intelligence Agent", page_icon="🏷️", layout="wide"
)

st.title("🏷️ Real-Time Price Comparison Agent")
st.caption(
    "Powered by Google Shopping Live Merchant Feed + Gemini (Location-Aware)"
)

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

INDIAN_STATES = [
    "All India (Default)",
    "Andhra Pradesh",
    "Assam",
    "Bihar",
    "Chandigarh",
    "Chhattisgarh",
    "Delhi",
    "Goa",
    "Gujarat",
    "Haryana",
    "Himachal Pradesh",
    "Jharkhand",
    "Karnataka",
    "Kerala",
    "Madhya Pradesh",
    "Maharashtra",
    "Odisha",
    "Punjab",
    "Rajasthan",
    "Tamil Nadu",
    "Telangana",
    "Uttar Pradesh",
    "Uttarakhand",
    "West Bengal",
]

# Side-by-side input bar
col1, col2, col3 = st.columns([3, 1.5, 1])

with col1:
  product = st.text_input(
      "Product + Size/Variant",
      placeholder="e.g., Kissan Ketchup 450g, PS5 Slim Disc, Sony WH-1000XM5",
  )
with col2:
  selected_state = st.selectbox("State / Region (Optional)", INDIAN_STATES)
with col3:
  pincode = st.text_input(
      "Pincode (Optional)", placeholder="e.g., 700027", max_chars=6
  )

st.caption(
    "💡 Tip: Include weight/storage (e.g., '450g' or '1TB') for exact variant"
    " matching. Leave State on 'All India' for national pricing."
)


# Caches results for 12 hours per product + location combination
@st.cache_data(ttl=43200, show_spinner=False)
def fetch_shopping_feed(product_name, state, pin, api_key):
  headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}

  # Append pincode to query if provided, otherwise use clean product name
  query_str = f"{product_name} {pin}".strip() if pin else product_name

  payload = {"q": query_str, "gl": "in", "hl": "en", "num": 15}

  # Only add geo-location parameter if user selected a specific state
  if state != "All India (Default)":
    payload["location"] = f"{state}, India"

  res = requests.post(
      "https://google.serper.dev/shopping",
      headers=headers,
      json=payload,
      timeout=10,
  ).json()

  # Fallback: If adding a 6-digit pincode made the search too narrow (0 results), re-run without pincode
  if not res.get("shopping") and pin:
    payload["q"] = product_name
    res = requests.post(
        "https://google.serper.dev/shopping",
        headers=headers,
        json=payload,
        timeout=10,
    ).json()

  records = []
  for item in res.get("shopping", []):
    records.append(
        f"Product Title: {item.get('title')} | "
        f"Retailer: {item.get('source')} | "
        f"Live Feed Price: {item.get('price')} | "
        f"Delivery: {item.get('delivery', 'Standard')} | "
        f"Direct Link: {item.get('link')}"
    )
  return "\n".join(records)


if st.button("Find Lowest Price", type="primary"):
  if not gemini_key or not serper_key:
    st.error("Please ensure both GEMINI_API_KEY and SERPER_API_KEY are set.")
  elif not product.strip():
    st.warning("Please enter a product name.")
  else:
    location_label = (
        f"{selected_state}"
        + (f" ({pincode})" if pincode.strip() else "")
        if selected_state != "All India (Default)"
        else "All India"
    )
    with st.spinner(
        f"Checking live Google Shopping merchant feeds for {location_label}..."
    ):
      try:
        search_context = fetch_shopping_feed(
            product.strip().lower(),
            selected_state,
            pincode.strip(),
            serper_key,
        )

        if not search_context.strip():
          st.warning(
              "No live merchant listings found. Try a broader product name."
          )
        else:
          client = genai.Client(api_key=gemini_key)

          prompt = f"""
                    You are a strict e-commerce price auditor for India.
                    Below is live merchant feed data from Google Shopping India for: "{product}" (Region context: {location_label}).

                    LIVE MERCHANT FEED DATA:
                    {search_context}

                    STRICT RULES:
                    1. EXACT PACK SIZE / VARIANT SEPARATION: Always include the exact weight, volume, pack count, or storage size (e.g., "450g", "2 x 225g", "1kg", "1TB") in the Product Title column. Never mix up a combo pack with a single pack.
                    2. ZERO HALLUCINATION: Report ONLY the exact 'Live Feed Price' and 'Direct Link' from the data above.
                    3. FILTER OUT ACCESSORIES: Ignore unrelated cables, covers, or accessories.
                    4. Output a clean Markdown table sorted from lowest price to highest:
                       | Product & Exact Size/Variant | Retailer | Live Feed Price (₹) | Delivery Info | Direct Link |
                       Format the link as [Buy Here](exact_url_from_data).
                    5. In your 'Bottom-Line Verdict', highlight the cheapest option for the primary variant requested.
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
                f"✅ Audit Trail: Raw Google Shopping Feed ({location_label})"
            ):
              st.text(search_context)
          else:
            st.error("Gemini servers are temporarily busy. Please try again.")

      except Exception as e:
        st.error(f"Error fetching live data: {e}")
