import time
from google import genai
import requests
import streamlit as st

st.set_page_config(
    page_title="AI Travel Hacking Toolkit", page_icon="✈️", layout="wide"
)

st.title("✈️ AI Travel Hacking & Points Optimizer")
st.caption(
    "Web UI powered by borski/travel-hacking-toolkit live GitHub data + Gemini"
)

gemini_key = (
    st.secrets.get("GEMINI_API_KEY")
    if "GEMINI_API_KEY" in st.secrets
    else st.sidebar.text_input("Gemini API Key", type="password")
)
serper_key = (
    st.secrets.get("SERPER_API_KEY")
    if "SERPER_API_KEY" in st.secrets
    else st.sidebar.text_input("Serper API Key (Optional)", type="password")
)

BORSKI_RAW_BASE = (
    "https://raw.githubusercontent.com/borski/travel-hacking-toolkit/main"
)


# Pulls live JSON databases directly from borski/travel-hacking-toolkit on GitHub
@st.cache_data(ttl=86400, show_spinner=False)
def load_toolkit_data():
  files = {
      "sweet_spots": f"{BORSKI_RAW_BASE}/data/sweet-spots.json",
      "transfer_partners": f"{BORSKI_RAW_BASE}/data/transfer-partners.json",
      "points_valuations": f"{BORSKI_RAW_BASE}/data/points-valuations.json",
      "alliances": f"{BORSKI_RAW_BASE}/data/alliances.json",
  }
  loaded = {}
  for name, url in files.items():
    try:
      r = requests.get(url, timeout=10)
      if r.status_code == 200:
        loaded[name] = r.text[:12000]  # Keep within fast token budget
    except Exception:
      loaded[name] = "Unavailable"
  return loaded


@st.cache_data(ttl=43200, show_spinner=False)
def fetch_live_flight_baseline(origin, dest, dates, api_key):
  if not api_key:
    return "No Serper key provided; estimate standard cash fares."
  try:
    res = requests.post(
        "https://google.serper.dev/search",
        headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
        json={
            "q": (
                f"flights from {origin} to {dest} {dates} price Google Flights"
                " Skyscanner"
            ),
            "num": 8,
        },
        timeout=10,
    ).json()
    return "\n".join([
        f"{i.get('title')}: {i.get('snippet')}" for i in res.get("organic", [])
    ])
  except Exception:
    return ""


col1, col2, col3, col4 = st.columns(4)
with col1:
  origin = st.text_input(
      "Origin (Airport/City)", placeholder="e.g., DEL, CCU, SFO"
  )
with col2:
  dest = st.text_input(
      "Destination (Airport/City)", placeholder="e.g., NRT, LHR, CDG"
  )
with col3:
  dates = st.text_input("Dates / Month", placeholder="e.g., Dec 2026")
with col4:
  cabin = st.selectbox(
      "Cabin Class", ["Economy", "Premium Economy", "Business", "First"]
  )

points_info = st.text_input(
    "Your Points / Miles / Cards (Optional — supports US & Indian programs)",
    placeholder=(
        "e.g., 100k Chase UR, 80k Amex MR, HDFC Infinia, Axis Atlas, or leave"
        " blank for best sweet spots"
    ),
)

if st.button("Run Travel Hacking Analysis", type="primary"):
  if not gemini_key:
    st.error("Please provide a Gemini API Key in Secrets or the sidebar.")
  elif not origin.strip() or not dest.strip():
    st.warning("Please enter both an Origin and a Destination.")
  else:
    with st.spinner(
        "Loading borski/travel-hacking-toolkit databases & calculating optimal"
        " redemptions..."
    ):
      toolkit_data = load_toolkit_data()
      live_flights = fetch_live_flight_baseline(
          origin, dest, dates, serper_key
      )

      prompt = f"""
            You are the AI Travel Hacker Agent powered by `borski/travel-hacking-toolkit`.
            Plan and optimize this trip using the official toolkit reference data below:
            - Route: {origin} to {dest}
            - Dates: {dates or "Flexible"}
            - Cabin: {cabin}
            - User's Points/Cards: {points_info or "Show best overall award sweet spots & transfer paths"}

            LIVE CASH FLIGHT BASELINE:
            {live_flights}

            TOOLKIT REFERENCE DATA (FROM GITHUB):
            1. SWEET SPOTS DB: {toolkit_data.get('sweet_spots', '')}
            2. TRANSFER PARTNERS DB: {toolkit_data.get('transfer_partners', '')}
            3. POINTS VALUATIONS (CPP FLOORS): {toolkit_data.get('points_valuations', '')}
            4. ALLIANCES DB: {toolkit_data.get('alliances', '')}

            MANDATORY WORKFLOW (FROM BORSKI TRIP-PLANNER & TRIP-CALCULATOR SKILLS):
            1. **Trip Cost & Strategy Matrix**: Output a Markdown table comparing:
               | Booking Strategy | Program / Airline Alliance | Est. Miles / Points Needed | Est. Cash / Taxes | Effective Value (CPP) | Verdict |
            2. **Award Sweet Spots & Transfer Paths**: Highlight the best partner award sweet spots for this route (e.g., Star Alliance, Oneworld, SkyTeam) and which credit card currencies (US cards from the JSON, plus Indian cards like Amex/HDFC/Axis if relevant to the route) transfer to them.
            3. **Cash vs. Points Math**: Using the formula `CPP = (Cash Price - Award Taxes) / Points * 100`, state whether the user should pay cash or burn points compared against the floor valuations.
            4. **Actionable Booking Checklist**: Give a 3-step checklist (which site to search availability on first, hold rules, and transfer warnings).
            """

      client = genai.Client(api_key=gemini_key)
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
        with st.expander(
            "📂 View Live JSON Data Loaded from borski/travel-hacking-toolkit"
        ):
          st.write("Successfully synced directly from GitHub `main` branch:")
          st.json({k: f"{len(v)} chars loaded" for k, v in toolkit_data.items()})
      else:
        st.error("Gemini servers are temporarily busy. Please try again.")
