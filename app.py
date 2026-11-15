import re
import time
from google import genai
import requests
import streamlit as st

st.set_page_config(
    page_title="Retail Price Intelligence Agent", page_icon="🏷️", layout="wide"
)

st.title("🏷️ Real-Time Price Comparison Agent")
st.caption("Direct Retailer Product Pages Only • Strict Specification & Link Filter")

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
    "All India (Default)", "Andhra Pradesh", "Assam", "Bihar", "Chandigarh",
    "Chhattisgarh", "Delhi", "Goa", "Gujarat", "Haryana", "Himachal Pradesh",
    "Jharkhand", "Karnataka", "Kerala", "Madhya Pradesh", "Maharashtra",
    "Odisha", "Punjab", "Rajasthan", "Tamil Nadu", "Telangana",
    "Uttar Pradesh", "Uttarakhand", "West Bengal",
]

col1, col2, col3 = st.columns([3, 1.5, 1])
with col1:
    product = st.text_input(
        "Product & Desired Specification",
        placeholder="e.g., Kissan Ketchup 800g+, PS5 Slim Disc, Sony WH-1000XM5",
    )
with col2:
    selected_state = st.selectbox("State / Region (Optional)", INDIAN_STATES)
with col3:
    pincode = st.text_input("Pincode (Optional)", placeholder="e.g., 700027", max_chars=6)


def call_gemini(client, prompt):
    models_to_try = ["gemini-3.5-flash-lite", "gemini-3.8-flash"]
    for model_name in models_to_try:
        for _ in range(2):
            try:
                res = client.models.generate_content(model=model_name, contents=prompt)
                if res and res.text:
                    return res.text.strip()
            except Exception as err:
                if "503" in str(err) or "UNAVAILABLE" in str(err):
                    time.sleep(1.5)
                    continue
                raise err
    return None


@st.cache_data(ttl=43200, show_spinner=False)
def fetch_verified_retail_pages(search_query, state, api_key):
    headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}

    # Restrict strictly to major Indian e-commerce websites with real checkout pages
    sites = (
        "(site:amazon.in OR site:flipkart.com OR site:jiomart.com OR "
        "site:bigbasket.com OR site:blinkit.com OR site:zepto.com OR "
        "site:croma.com OR site:reliancedigital.in OR site:myntra.com)"
    )
    full_query = f"{search_query} price ₹ {sites}"

    payload = {"q": full_query, "gl": "in", "hl": "en", "num": 15}
    if state != "All India (Default)":
        payload["location"] = f"{state}, India"

    res = requests.post(
        "https://google.serper.dev/search",
        headers=headers,
        json=payload,
        timeout=10,
    ).json()

    valid_records = []
    price_regex = re.compile(r"(?:₹|Rs\.?|INR)\s?[\d,]+", re.IGNORECASE)

    for item in res.get("organic", []):
        link = item.get("link", "")
        title = item.get("title", "")
        snippet = item.get("snippet", "")
        rich_price = item.get("price", "")

        # 1. HARD FILTER: Reject missing links, Google redirect pages, and generic search bars
        if not link or "google.com" in link:
            continue
        if any(bad in link for bad in ["/s?", "/search?", "/q/", "searchB?"]):
            continue

        # 2. HARD FILTER: Reject listings that do not contain an explicit Rupee price
        combined_text = f"{title} {rich_price} {snippet}"
        found_prices = price_regex.findall(combined_text)
        if not rich_price and not found_prices:
            continue

        price_display = rich_price if rich_price else ", ".join(found_prices)
        valid_records.append(
            f"Title: {title} | Extracted Price(s): {price_display} | "
            f"Snippet: {snippet} | Direct Store URL: {link}"
        )

    return "\n".join(valid_records)


if st.button("Find Lowest Price", type="primary"):
    if not gemini_key or not serper_key:
        st.error("Please ensure both GEMINI_API_KEY and SERPER_API_KEY are set.")
    elif not product.strip():
        st.warning("Please enter a product name.")
    else:
        with st.spinner("Translating specifications and scanning direct retailer product pages..."):
            try:
                client = genai.Client(api_key=gemini_key)

                # Step 1: Convert natural phrases like "800g plus" into exact retail pack sizes
                query_prompt = f"""
                Convert this user product request into a concise Google Search keyword string for Indian e-commerce: "{product}"
                - If the user specifies a range like "800g plus", "above 800g", or "1.1L", replace that phrase with actual commercial pack sizes sold in India using OR (e.g., Kissan Ketchup ("850g" OR "950g" OR "1kg" OR "1.1kg")).
                - Output ONLY the plain search string, nothing else.
                """
                optimized_query = call_gemini(client, query_prompt) or product.strip()

                # Step 2: Fetch direct store URLs (1 credit, cached)
                search_context = fetch_verified_retail_pages(
                    optimized_query, selected_state, serper_key
                )

                if not search_context.strip():
                    st.warning("No direct product pages with verified prices matched that exact specification. Try broadening your search slightly.")
                else:
                    # Step 3: Strict filtering and table generation
                    audit_prompt = f"""
                    You are a strict Indian e-commerce price auditor.
                    User's original request & specification: "{product}"

                    VERIFIED DIRECT RETAILER PAGES:
                    {search_context}

                    MANDATORY FILTERING RULES:
                    1. STRICT SPECIFICATION MATCH: If the user asked for a specific size/weight/model (e.g., "800g+" or "1.1L" or "Disc Edition"), COMPLETELY EXCLUDE any listing that is smaller or different (e.g., exclude 15g, 200g, 415g, 450g packs).
                    2. NO MISSING LINKS OR PRICES: Every row MUST have a numeric Rupee price (₹) and a valid clickable 'Direct Store URL' from the data above. If a listing lacks either, exclude it.
                    3. Output a clean Markdown table sorted from lowest price to highest:
                       | Exact Product & Pack Size | Retailer | Price (₹) | Direct Product Page |
                       Format the link as [Buy on Retailer](exact_url_from_data).
                    4. Finish with a 2-sentence 'Best Deal Verdict' naming the cheapest matching option and its price per unit/pack.
                    """

                    final_output = call_gemini(client, audit_prompt)
                    if final_output:
                        st.caption(f"🔍 **Search Query Used:** `{optimized_query}`")
                        st.markdown(final_output)
                        with st.expander("✅ Audit Trail: View Pre-Filtered Direct Retailer Pages"):
                            st.text(search_context)
                    else:
                        st.error("Gemini servers are temporarily busy. Please try again.")

            except Exception as e:
                st.error(f"Error fetching live data: {e}")
