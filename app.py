import json
from datetime import date, timedelta
import requests
import streamlit as st

st.set_page_config(page_title="60-Day Reward Seat Finder", page_icon="✈️", layout="wide")
st.title("✈️ 60-Day Reward Seat Availability")
st.caption("Direct connection to the public Seats.aero MCP server — no API keys or points calculator needed.")

MCP_URL = "https://seats.aero/mcp"

def parse_mcp_response(resp):
    """Parses either standard JSON or Server-Sent Events (SSE) from the MCP server."""
    if not resp.text or not resp.text.strip():
        return {}
    content_type = resp.headers.get("Content-Type", "")
    if "text/event-stream" in content_type or resp.text.lstrip().startswith(("event:", "data:")):
        last_json = {}
        for line in resp.text.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                data_str = line[len("data:"):].strip()
                if data_str:
                    try:
                        last_json = json.loads(data_str)
                    except json.JSONDecodeError:
                        pass
        return last_json
    try:
        return resp.json()
    except Exception:
        return {"raw_text": resp.text}

def mcp_post(http_session, method, params=None, session_id=None, req_id=None):
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "User-Agent": "streamlit-award-finder/1.0",
    }
    if session_id:
        headers["Mcp-Session-Id"] = session_id

    payload = {"jsonrpc": "2.0", "method": method}
    if req_id is not None:
        payload["id"] = req_id
    if params is not None:
        payload["params"] = params

    resp = http_session.post(MCP_URL, headers=headers, json=payload, timeout=30)
    new_session_id = (
        resp.headers.get("Mcp-Session-Id")
        or resp.headers.get("mcp-session-id")
        or session_id
    )
    return resp.status_code, parse_mcp_response(resp), new_session_id

def build_tool_arguments(tool, origin, destination, cabin, start_date_str, end_date_str):
    """Maps inputs using exact property names and never puts strings into integer/number fields."""
    schema = tool.get("inputSchema", {})
    props = schema.get("properties", {})
    args = {}

    ORIGIN_KEYS = {"origin", "origins", "origin_airport", "origin_airports", "from_airport", "departure_airport"}
    DEST_KEYS = {"destination", "destinations", "destination_airport", "destination_airports", "to_airport", "arrival_airport"}
    START_DATE_KEYS = {"start_date", "startdate", "date_from", "from_date", "departure_date", "date"}
    END_DATE_KEYS = {"end_date", "enddate", "date_to", "to_date"}
    CABIN_KEYS = {"cabin", "cabins", "cabin_class"}  # Strictly excludes min_cabin_pct!

    for prop_name, prop_def in props.items():
        p_low = prop_name.lower()
        prop_type = prop_def.get("type", "string")

        # Never populate integer, number, or boolean fields with string inputs
        if prop_type in ("integer", "number", "boolean"):
            continue

        def format_val(val):
            if prop_type == "array":
                return [x.strip() for x in val.split(",") if x.strip()]
            return val

        if p_low in ORIGIN_KEYS:
            args[prop_name] = format_val(origin)
        elif p_low in DEST_KEYS:
            args[prop_name] = format_val(destination)
        elif p_low in START_DATE_KEYS:
            args[prop_name] = start_date_str
        elif p_low in END_DATE_KEYS:
            args[prop_name] = end_date_str
        elif p_low in CABIN_KEYS and cabin != "Any":
            args[prop_name] = format_val(cabin)

    return args

def extract_json_rows(text_val):
    """Extracts JSON objects whether returned as a JSON array, dict, or line-by-line JSON objects."""
    rows = []
    try:
        parsed = json.loads(text_val)
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            if isinstance(parsed.get("data"), list):
                return parsed["data"]
            return [parsed]
    except json.JSONDecodeError:
        pass

    for line in text_val.splitlines():
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return rows

# --- Search UI ---
col1, col2, col3, col4 = st.columns([2, 2, 2, 2])
with col1:
    origin = st.text_input("Origin Airport (IATA)", value="DEL").strip().upper()
with col2:
    destination = st.text_input("Destination Airport (IATA)", value="SIN").strip().upper()
with col3:
    cabin = st.selectbox("Cabin Class", ["Any", "economy", "premium", "business", "first"])
with col4:
    days_ahead = st.slider("Search Window (Days)", min_value=7, max_value=60, value=60)

st.caption("💡 Tip: Seats.aero tracks major international hubs (`DEL`, `BOM`, `BLR`, `MAA`, `HYD`). Smaller airports like `CCU` may have limited or no cached coverage depending on the airline program.")

start_date_str = date.today().isoformat()
end_date_str = (date.today() + timedelta(days=days_ahead)).isoformat()

if st.button("Search 60-Day Award Seats", type="primary"):
    status_box = st.status("Searching 60-day reward seat inventory...", expanded=True)

    try:
        http_session = requests.Session()

        # 1. Initialize MCP session
        _, _, session_id = mcp_post(
            http_session,
            "initialize",
            params={
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "streamlit-award-finder", "version": "1.0.0"},
            },
            req_id=1,
        )

        # 2. Confirm initialization
        mcp_post(http_session, "notifications/initialized", session_id=session_id, req_id=None)

        # 3. Fetch tools and pick get_flights directly
        _, tools_res, session_id = mcp_post(
            http_session, "tools/list", params={}, session_id=session_id, req_id=2
        )
        tools = tools_res.get("result", {}).get("tools", [])

        if not tools:
            status_box.update(label="No tools returned by server", state="error")
            st.stop()

        search_tool = next((t for t in tools if t.get("name") == "get_flights"), tools[0])
        tool_name = search_tool["name"]
        args = build_tool_arguments(search_tool, origin, destination, cabin, start_date_str, end_date_str)

        status_box.write(f"Calling **`{tool_name}`** with `{json.dumps(args)}`")

        # 4. Call get_flights
        _, call_res, _ = mcp_post(
            http_session,
            "tools/call",
            params={"name": tool_name, "arguments": args},
            session_id=session_id,
            req_id=3,
        )
        status_box.update(label=f"Search complete via `{tool_name}`!", state="complete", expanded=False)

        if call_res.get("error"):
            st.error(f"MCP Server Error: {call_res['error']}")

        content_items = call_res.get("result", {}).get("content", [])
        all_rows = []
        raw_texts = []

        for item in content_items:
            text_val = item.get("text", "")
            if text_val:
                raw_texts.append(text_val)
                all_rows.extend(extract_json_rows(text_val))

        if all_rows:
            st.subheader(f"✈️ Found {len(all_rows)} Reward Seat Listings ({origin} → {destination})")
            st.dataframe(all_rows, use_container_width=True)
        elif raw_texts:
            for t in raw_texts:
                st.markdown(t)
        else:
            st.warning(f"No reward seats returned for {origin} → {destination} between {start_date_str} and {end_date_str}.")

        with st.expander("🔍 Inspect Tool Schema & Raw MCP Output"):
            st.write("**Arguments Sent:**")
            st.json(args)
            st.write("**`get_flights` Schema:**")
            st.json(search_tool)
            st.write("**Raw `tools/call` Response:**")
            st.json(call_res)

    except Exception as e:
        status_box.update(label="Connection failed", state="error", expanded=True)
        st.exception(e)

