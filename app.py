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

def pick_route_search_tool(tools):
    """Finds the tool that accepts origin/destination airport codes (and NOT a flight reference ID)."""
    scored_tools = []
    for t in tools:
        name = t.get("name", "").lower()
        desc = t.get("description", "").lower()
        schema = t.get("inputSchema", {})
        props = {k.lower(): v for k, v in schema.get("properties", {}).items()}
        required = [r.lower() for r in schema.get("required", [])]

        # Skip tools that require a specific flight/trip/availability reference ID
        if any(bad in r for r in required for bad in ["id", "ref", "trip"]):
            continue
        # Skip live search or alert tools (Pro/Commercial only)
        if "live" in name or "alert" in name or "refresh" in name:
            continue

        score = 0
        if any("origin" in p or "departure" in p or "from" in p for p in props):
            score += 5
        if any("dest" in p or "arrival" in p or "to" in p for p in props):
            score += 5
        if "search" in name or "cached" in name or "avail" in name:
            score += 3
        if "search" in desc or "cached" in desc:
            score += 1

        scored_tools.append((score, t))

    scored_tools.sort(key=lambda x: x[0], reverse=True)
    return scored_tools[0][1] if scored_tools else tools[0]

def build_tool_arguments(tool, origin, destination, cabin, start_date_str, end_date_str):
    """Maps user inputs onto the exact property names and types defined in the tool's JSON schema."""
    schema = tool.get("inputSchema", {})
    props = schema.get("properties", {})
    args = {}

    for prop_name, prop_def in props.items():
        p_low = prop_name.lower()
        prop_type = prop_def.get("type", "string")

        def format_val(val):
            if prop_type == "array":
                return [x.strip() for x in val.split(",") if x.strip()]
            return val

        if any(k in p_low for k in ["origin", "from_airport", "departure_airport", "origins"]) and "region" not in p_low:
            args[prop_name] = format_val(origin)
        elif any(k in p_low for k in ["dest", "to_airport", "arrival_airport", "destinations"]) and "region" not in p_low:
            args[prop_name] = format_val(destination)
        elif any(k in p_low for k in ["start_date", "startdate", "date_from", "from_date", "departure_date"]):
            args[prop_name] = start_date_str
        elif any(k in p_low for k in ["end_date", "enddate", "date_to", "to_date"]):
            args[prop_name] = end_date_str
        elif "date" == p_low:
            args[prop_name] = start_date_str
        elif "cabin" in p_low and cabin != "Any":
            args[prop_name] = format_val(cabin)

    return args

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
    status_box = st.status("Connecting to Seats.aero MCP server...", expanded=True)

    try:
        http_session = requests.Session()

        # 1. Initialize MCP session
        code, init_res, session_id = mcp_post(
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

        # 3. Fetch tools
        code, tools_res, session_id = mcp_post(
            http_session, "tools/list", params={}, session_id=session_id, req_id=2
        )
        tools = tools_res.get("result", {}).get("tools", [])

        if not tools:
            status_box.update(label="No tools returned by server", state="error")
            st.json(tools_res)
            st.stop()

        # 4. Pick the route search tool (ignoring flight-reference lookup tools)
        search_tool = pick_route_search_tool(tools)
        tool_name = search_tool["name"]
        args = build_tool_arguments(search_tool, origin, destination, cabin, start_date_str, end_date_str)

        status_box.write(f"Available tools: `{[t.get('name') for t in tools]}`")
        status_box.write(f"Selected route search tool: **`{tool_name}`**")
        status_box.write(f"Sending arguments: `{json.dumps(args)}`")

        # 5. Call the route search tool
        code, call_res, _ = mcp_post(
            http_session,
            "tools/call",
            params={"name": tool_name, "arguments": args},
            session_id=session_id,
            req_id=3,
        )
        status_box.update(label="Search complete!", state="complete", expanded=False)

        result_block = call_res.get("result", {})
        content_items = result_block.get("content", [])

        if call_res.get("error"):
            st.error(f"MCP Server Error: {call_res['error']}")

        for item in content_items:
            text_val = item.get("text", "")
            if not text_val:
                continue
            try:
                parsed_json = json.loads(text_val)
                if isinstance(parsed_json, list):
                    if parsed_json:
                        st.subheader(f"Found {len(parsed_json)} Award Flights ({origin} → {destination})")
                        st.dataframe(parsed_json, use_container_width=True)
                    else:
                        st.warning(f"0 cached seats found for {origin} → {destination}. Try `DEL` → `SIN` or `BOM` → `LHR`.")
                elif isinstance(parsed_json, dict) and isinstance(parsed_json.get("data"), list):
                    rows = parsed_json["data"]
                    if rows:
                        st.subheader(f"Found {len(rows)} Award Flights ({origin} → {destination})")
                        st.dataframe(rows, use_container_width=True)
                    else:
                        st.warning(f"0 cached seats found for {origin} → {destination}. Try `DEL` → `SIN` or `BOM` → `LHR`.")
                else:
                    st.json(parsed_json)
            except json.JSONDecodeError:
                st.markdown(text_val)

        with st.expander("🔍 Inspect All MCP Tools & Raw Response"):
            st.write("**Selected Tool & Schema:**")
            st.json(search_tool)
            st.write("**Arguments Sent:**")
            st.json(args)
            st.write("**All Tools Exposed by Server:**")
            st.json(tools)
            st.write("**Raw `tools/call` Response:**")
            st.json(call_res)

    except Exception as e:
        status_box.update(label="Connection failed", state="error", expanded=True)
        st.exception(e)
        
