import streamlit as st
from google import genai
from google.genai import types

st.set_page_config(page_title="Retail Price Intelligence Agent", page_icon="🏷️", layout="centered")

st.title("🏷️ Real-Time Price Comparison Agent")
st.caption("Powered by Gemini 3.8 Flash + Live Google Search Grounding")

# Retrieve API key securely from Streamlit Cloud Secrets, or fall back to sidebar input
api_key = st.secrets.get("GEMINI_API_KEY") if "GEMINI_API_KEY" in st.secrets else st.sidebar.text_input("Enter Gemini API Key", type="password")

product = st.text_input("Enter product name (e.g., Xbox Series X 1TB, Sony WH-1000XM5):")

if st.button("Find Lowest Price", type="primary"):
    if not api_key:
        st.error("Please provide a Gemini API Key to run the agent.")
    elif not product.strip():
        st.warning("Please enter a product name.")
    else:
        with st.spinner("Agent is searching Amazon, Flipkart, and other retailers..."):
            try:
                client = genai.Client(api_key=api_key)

                prompt = f"""
                You are a procurement and price intelligence agent.
                The user wants to find current prices in India (in INR / ₹) for: "{product}".

                Instructions:
                1. If the input is specific (e.g., "Xbox Series X 1TB"), search Amazon.in, Flipkart, and major Indian electronics retailers, then compare live face-value listed prices (excluding card discounts) for that exact model.
                2. If the input is broad (e.g., "PlayStation 5" or "Xbox"), identify the main current retail variants (e.g., Disc vs. Digital Edition, or Series X vs. Series S) and compare each variant separately across platforms so you never mix different models.
                3. Calculate the price variance/savings between the highest and lowest retailer for each model.
                4. Output a clean Markdown table:
                   | Model / Variant | Platform | Listed Price (₹) | In Stock? |
                5. Provide a concise purchase recommendation highlighting the lowest-cost vendor.
                """

                response = client.models.generate_content(
                    model="gemini-3.8-flash",
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        tools=[types.Tool(google_search=types.GoogleSearch())],
                        temperature=0.2,
                    ),
                )

                st.markdown(response.text)

            except Exception as e:
                st.error(f"Error fetching prices: {e}")
