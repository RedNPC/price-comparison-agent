import streamlit as st
from google import genai
from google.genai import types

st.set_page_config(page_title="Retail Price Intelligence Agent", page_icon="🏷️", layout="centered")

st.title("🏷️ Real-Time Price Comparison Agent")
st.caption("Powered by Gemini 2.5 Flash + Live Google Search Grounding")

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
                You are a procurement and price comparison agent.
                Find the current live listed price in India (in INR / ₹) for: "{product}".
                Search specifically across Amazon.in, Flipkart, and other major Indian electronics retailers.

                Instructions:
                1. Extract the current standard face-value listed price on each platform (exclude bank/card discounts).
                2. Identify which platform is currently selling it for the lowest price.
                3. Calculate the absolute variance/savings (Highest Price - Lowest Price).
                4. Output a clean Markdown table:
                   | Platform | Listed Price (₹) | In Stock? |
                5. Provide a direct, one-sentence purchase recommendation highlighting the cheapest vendor.
                """

                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        tools=[types.Tool(google_search=types.GoogleSearch())],
                        temperature=0.2,
                    ),
                )

                st.markdown(response.text)

            except Exception as e:
                st.error(f"Error fetching prices: {e}")
