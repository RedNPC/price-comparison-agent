import time
from urllib.parse import quote_plus
from google import genai
import requests
import streamlit as st

st.set_page_config(
    page_title="Retail Price Intelligence Agent", page_icon="🏷️", layout="wide"
)

st.title("🏷️ Real-Time Price Comparison Agent")
st.caption("Hybrid Merchant Feed + Direct Store Link Engine")

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

# Trusted major Indian retailers (blocks random local kirana shops)
TRUSTED_STORES = [
    "amazon", "flipkart", "bigbasket", "jiomart", "blinkit", "zepto",
    "swiggy", "instamart", "croma", "reliance", "myntra", "nykaa",
    "tatacliq", "dmart", "shopsy", "vijaysales", "ajio",
]

col1, col2, col3 = st.columns([3, 1.5, 1])
with col1:
    product = st.text_input(
        "Product & Desired Specification",
        placeholder="e.g., Kissan Tomato Ketchup 850g, PS5 Slim Disc, Sony WH-1000XM5",
    )
with col2:
    selected_state = st.selectbox("State / Region (Optional)", INDIAN_STATES)
with col3:
    pincode = st.text_input("Pincode (Optional)", placeholder="e.g., 700048", max_chars=6)


def get_fallback_store_url(store_name, title):
    s = store_name.lower()
    q = quote_plus(title)
    if "amazon" in s:
        return f"https://www.amazon.in/s?k={q}"
    if "flipkart" in s or "shopsy" in s:
        return f"https://www.flipkart.com/search?q={q}"
    if "bigbasket" in s:
        return f"https://www.bigbasket.com/ps/?q={q}"
    if "jiomart" in s:
        return f"https://www.jiomart.com/search/{q}"
    if "croma" in s:
        return f"https://www.croma.com/searchB?q={q}"
    if "reliance" in s:
        return f"https://www.reliancedigital.in/search?q={q}"
    if "myntra" in s:
        return f"https://www.myntra.com/{q}"
    if "nykaa" in s:
        return f"https://www.nykaa.com/search/result/?q={q}"
    if "blinkit" in s:
        return f"https://blinkit.com/s/?q={q}"
    if "zepto" in s:
        return f"https://www.zeptonow.com/search?query={q}"
    return f"https://www.google.com/search?q={quote_plus(store_name + ' ' + title)}"


@st.cache_data(ttl=43200, show_spinner=False)
def fetch_hybrid_price_data(product_query, state, api_key):
    headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}

    shop_payload = {"q": product_query, "gl": "in", "hl": "en", "num": 20}
    web_payload = {
        "q": f"{product_query} buy online India Amazon Flipkart BigBasket JioMart Croma",
        "gl": "in",
        "hl": "en",
        "num": 10,
    }

    if state != "All India (Default)":
        shop_payload["location"] = f"{state}, India"
        web_payload["location"] = f"{state}, India"

    # 1. Fetch live merchant prices from Google Shopping
    shop_res = requests.post(
        "https://google.serper.dev/shopping", headers=headers, json=shop_payload, timeout=10
    ).json()

    # 2. Fetch direct product page URLs from Google Organic Search
    web_res = requests.post(
        "https://google.serper.dev/search", headers=headers, json=web_payload, timeout=10
    ).json()

    # Map direct organic product URLs by store domain
    direct_urls = {}
    for item in web_res.get("organic", []):
        link = item.get("link", "")
        if not link or "google.com" in link:
            continue
        for store in TRUSTED_STORES:
            if store in link.lower() and store not in direct_urls:
                direct_urls[store] = link

    records = []
    # Process live Google Shopping items (filtered to trusted stores)
    for item in shop_res.get("shopping", []):
        source = item.get("source", "")
        title = item.get("title", "")
        price = item.get("price", "")
        raw_link = item.get("link", "")

        if not price:
            continue

        matched_store = next((s for s in TRUSTED_STORES if s in source.lower()), None)
        if not matched_store:
            continue

        # Use direct product link if valid; otherwise use matched organic URL or exact title store search
        if raw_link and "google.com" not in raw_link:
            final_url = raw_link
        elif matched_store in direct_urls:
            final_url = direct_urls[matched_store]
        else:
            final_url = get_fallback_store_url(source, title)

        records.append(
            f"[MERCHANT FEED] Title: {title} | Retailer: {source} | "
            f"Verified Price: {price} | Store Link: {final_url}"
        )

    # Also include direct organic results in case an item isn't in the Shopping tab
    for item in web_res.get("organic", []):
        link = item.get("link", "")
        title = item.get("title", "")
        snippet = item.get("snippet", "")
        price = item.get("price", "")
        if any(s in link.lower() for s in TRUSTED_STORES):
            records.append(
                f"[DIRECT WEB PAGE] Title: {title} | Price Info: {price} {snippet} | "
                f"Store Link: {link}"
            )

    return "\n".join(records)


if st.button("Find Lowest Price", type="primary"):
    if not gemini_key or not serper_key:
        st.error("Please ensure both GEMINI_API_KEY and SERPER_API_KEY are set.")
    elif not product.strip():
        st.warning("Please enter a product name.")
    else:
        location_label = selected_state if selected_state != "All India (Default)" else "All India"
        with st.spinner(f"Scanning major Indian retailers for {product}..."):
            try:
                search_context = fetch_hybrid_price_data(
                    product.strip(), selected_state, serper_key
                )

                if not search_context.strip():
                    st.warning("No listings found. Check your spelling and try again.")
                else:
                    client = genai.Client(api_key=gemini_key)

                    prompt = f"""
                    You are an Indian e-commerce price comparison agent (like PriceKart).
                    User Request: "{product}" (Region: {location_label})

                    LIVE RETAIL DATA:
                    {search_context}

                    INSTRUCTIONS:
                    1. Prioritize [MERCHANT FEED] entries because they contain live, structured prices from major retailers.
                    2. PACK SIZE / VARIANT ACCURACY: Always state the exact weight, volume, or model in the first column (e.g., "850g Pouch", "1kg", "Slim Disc"). If the user asked for a specific size (e.g., "800g+" or "1kg"), exclude smaller sizes like 200g or 450g.
                    3. EVERY ROW MUST HAVE A PRICE & CLICKABLE LINK: Never output "None" or "Check Site". Format every link in the final column as [Buy on Retailer](Store Link).
                    4. Sort the Markdown table from lowest price to highest:
                       | Product & Pack Size/Variant | Retailer | Live Price (₹) | Store Link |
                    5. End with a short 'Best Deal Verdict' highlighting the cheapest store for the target pack size.
                    """

                    models_to_try = ["gemini-3.5-flash-lite", "gemini-3.8-flash"]
                    response = None

                    for model_name in models_to_try:
                        try:
                            response = client.models.generate_content(
                                model=model_name, contents=prompt
                            )
                            if response and response.text:
                                break
                        except Exception as err:
                            if "503" in str(err) or "UNAVAILABLE" in str(err):
                                time.sleep(1.5)
                                continue
                            raise err

                    if response and response.text:
                        st.markdown(response.text)
                        with st.expander("✅ Audit Trail: View Raw Merchant Feed & Store Data"):
                            st.text(search_context)
                    else:
                        st.error("Gemini servers are temporarily busy. Please click again.")

            except Exception as e:
                st.error(f"Error fetching live data: {e}")
