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

start_date_str = date.today().isoformat()
end_date_str = (date.today() + timedelta(days=days_ahead)).isoformat()

if st.button("Search 60-Day Award Seats", type="primary"):
    status_box = st.status("Connecting to Seats.aero MCP server...", expanded=True)

    try:
        http_session = requests.Session()

        # 1. Initialize MCP session
        status_box.write("1️⃣ Sending `initialize` handshake...")
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
        status_box.write(f"   • HTTP {code} | Session ID: `{session_id or 'stateless'}`")

        # 2. Send required 'notifications/initialized' confirmation
        status_box.write("2️⃣ Sending `notifications/initialized`...")
        mcp_post(http_session, "notifications/initialized", session_id=session_id, req_id=None)

        # 3. List available MCP tools & inspect schema
        status_box.write("3️⃣ Fetching available search tools (`tools/list`)...")
        code, tools_res, session_id = mcp_post(
            http_session, "tools/list", params={}, session_id=session_id, req_id=2
        )
        tools = tools_res.get("result", {}).get("tools", [])

        if not tools:
            status_box.update(label="MCP server did not return any tools", state="error")
            st.error("Could not load tools from Seats.aero. Raw response below:")
            st.json(tools_res)
            st.stop()

        tool_names = [t.get("name") for t in tools]
        status_box.write(f"   • Discovered tools: `{', '.join(tool_names)}`")

        # Pick the primary flight search tool dynamically
        search_tool = next(
            (t for t in tools if any(k in t["name"].lower() for k in ["flight", "search", "avail", "award"])),
            tools[0],
        )
        tool_name = search_tool["name"]
        schema_props = search_tool.get("inputSchema", {}).get("properties", {})

        # Map our inputs to the exact parameter names expected by the tool's schema
        args = {}
        for prop_name in schema_props:
            p_low = prop_name.lower()
            if "origin" in p_low and "region" not in p_low:
                args[prop_name] = origin
            elif ("dest" in p_low or "arrival" in p_low) and "region" not in p_low:
                args[prop_name] = destination
            elif "start" in p_low and "date" in p_low:
                args[prop_name] = start_date_str
            elif "end" in p_low and "date" in p_low:
                args[prop_name] = end_date_str
            elif "cabin" in p_low and cabin != "Any":
                args[prop_name] = cabin

        status_box.write(f"4️⃣ Calling `{tool_name}` with `{json.dumps(args)}`...")
        code, call_res, _ = mcp_post(
            http_session,
            "tools/call",
            params={"name": tool_name, "arguments": args},
            session_id=session_id,
            req_id=3,
        )
        status_box.update(label="Search complete!", state="complete", expanded=False)

        # 4. Extract and display the results
        result_block = call_res.get("result", {})
        content_items = result_block.get("content", [])

        if call_res.get("error"):
            st.error(f"MCP Server Error: {call_res['error']}")

        rendered_any = False
        for item in content_items:
            text_val = item.get("text", "")
            if not text_val:
                continue
            rendered_any = True
            # Try parsing as JSON in case the tool returns structured flight objects
            try:
                parsed_json = json.loads(text_val)
                if isinstance(parsed_json, list) and len(parsed_json) > 0:
                    st.subheader(f"Found {len(parsed_json)} Award Results ({origin} → {destination})")
                    st.dataframe(parsed_json, use_container_width=True)
                elif isinstance(parsed_json, dict) and "data" in parsed_json and isinstance(parsed_json["data"], list):
                    rows = parsed_json["data"]
                    if rows:
                        st.subheader(f"Found {len(rows)} Award Results ({origin} → {destination})")
                        st.dataframe(rows, use_container_width=True)
                    else:
                        st.warning(f"No cached reward seats found between {origin} and {destination} for {start_date_str} to {end_date_str}. Try a major hub route like JFK -> LHR or SIN -> NRT to verify.")
                else:
                    st.json(parsed_json)
            except json.JSONDecodeError:
                # If the MCP server already formatted it as Markdown/text, render it directly
                st.markdown(text_val)

        if not rendered_any:
            st.warning("The query succeeded, but no text content was returned. Inspect the raw response below:")

        with st.expander("🔍 Inspect Raw MCP Response & Tool Schema"):
            st.write("**Selected Tool Schema:**")
            st.json(search_tool)
            st.write("**Raw `tools/call` Response:**")
            st.json(call_res)

    except Exception as e:
        status_box.update(label="Connection failed", state="error", expanded=True)
        st.exception(e)
        
