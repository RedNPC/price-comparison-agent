import json
from datetime import date, timedelta
import requests
import streamlit as st
from google import genai

st.set_page_config(page_title="60-Day Reward Seat Finder", page_icon="✈️", layout="wide")
st.title("✈️ 60-Day Reward Seat Availability")
st.caption("Powered by the public Seats.aero MCP endpoint — no points calculator, just open award seats.")

MCP_URL = "https://seats.aero/mcp"

# 1. Load Gemini API Key (from Streamlit Secrets or sidebar)
api_key = st.secrets.get("GEMINI_API_KEY", "")
if not api_key:
    api_key = st.sidebar.text_input("Gemini API Key", type="password")

def parse_mcp_response(resp):
    """Handles both standard JSON and SSE (text/event-stream) MCP responses."""
    content_type = resp.headers.get("Content-Type", "")
    if "text/event-stream" in content_type:
        for line in resp.text.splitlines():
            if line.startswith("data:"):
                data_str = line[len("data:"):].strip()
                if data_str:
                    return json.loads(data_str)
    return resp.json()

def mcp_request(method, params=None, session_id=None, req_id=1):
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if session_id:
        headers["Mcp-Session-Id"] = session_id

    payload = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        payload["params"] = params

    resp = requests.post(MCP_URL, headers=headers, json=payload, timeout=30)
    resp.raise_for_status()
    new_session_id = resp.headers.get("Mcp-Session-Id", session_id)
    return parse_mcp_response(resp), new_session_id

def fetch_60_day_availability(user_prompt, client):
    # Step A: Initialize keyless MCP session
    init_params = {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "streamlit-award-finder", "version": "1.0.0"},
    }
    _, session_id = mcp_request("initialize", init_params, req_id=1)

    # Step B: Fetch available MCP tools so arguments always match the live schema
    tools_res, session_id = mcp_request("tools/list", {}, session_id=session_id, req_id=2)
    tools = tools_res.get("result", {}).get("tools", [])

    today_str = date.today().isoformat()
    max_date_str = (date.today() + timedelta(days=60)).isoformat()

    # Step C: Have Gemini map the search into the exact MCP tool call
    planner_prompt = f"""
    Today is {today_str}. The free public tier covers departures from {today_str} to {max_date_str} (60 days).
    Available MCP tools:
    {json.dumps(tools)}

    User request: "{user_prompt}"

    Return ONLY a raw JSON object with keys "name" (the exact tool name for searching cached award flights)
    and "arguments" (matching that tool's inputSchema). Do not wrap in markdown fences.
    """
    plan_resp = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=planner_prompt,
    )
    cleaned_json = plan_resp.text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    tool_call = json.loads(cleaned_json)

    # Step D: Execute the MCP tool call against Seats.aero
    call_res, _ = mcp_request(
        "tools/call",
        {"name": tool_call["name"], "arguments": tool_call["arguments"]},
        session_id=session_id,
        req_id=3,
    )
    return call_res

# --- UI Layout ---
col1, col2, col3 = st.columns([2, 2, 2])
with col1:
    origin = st.text_input("Origin Airport(s) (IATA)", value="DEL, BOM")
with col2:
    destination = st.text_input("Destination Airport(s) (IATA)", value="SIN, LHR")
with col3:
    cabin = st.selectbox("Preferred Cabin", ["Any", "economy", "premium", "business", "first"])

custom_notes = st.text_input(
    "Optional date window or filter (within the next 60 days)",
    placeholder="e.g., anytime in December, at least 2 seats",
)

if st.button("Search 60-Day Award Seats", type="primary"):
    if not api_key:
        st.error("Please add your GEMINI_API_KEY in Streamlit Secrets or the sidebar.")
    else:
        client = genai.Client(api_key=api_key)
        query_text = f"Find award seat availability from {origin} to {destination} in {cabin} cabin within the next 60 days. {custom_notes}"
        
        with st.spinner("Querying live 60-day inventory from Seats.aero MCP..."):
            try:
                raw_mcp_data = fetch_60_day_availability(query_text, client)
                
                format_prompt = f"""
                Format the following raw Seats.aero MCP response into a clean Markdown table of available reward seats.
                Include ONLY: Date, Route, Operating Carrier / Program, Cabin, Seats Available, and Mileage Cost + Taxes (if listed).
                Do NOT include points valuation formulas, CPP calculations, or transfer partner advice.

                Raw data:
                {json.dumps(raw_mcp_data)}
                """
                final_output = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=format_prompt,
                )
                st.markdown(final_output.text)
                
                with st.expander("View Raw MCP JSON Response"):
                    st.json(raw_mcp_data)
            except Exception as e:
                st.error(f"Error fetching availability: {e}")
    
