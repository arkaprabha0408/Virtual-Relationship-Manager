from __future__ import annotations

import os

import pandas as pd
import requests
import streamlit as st

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")
TIMEOUT = 60

AGENT_BADGES = {
    "business_intel": "🧠 Business Intelligence",
    "product_expert": "🏦 Product Expert",
    "concierge": "🤝 Concierge",
}

st.set_page_config(page_title="Virtual Relationship Manager", layout="wide")


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _get(path: str, params: dict | None = None) -> dict | list | None:
    try:
        resp = requests.get(f"{BACKEND_URL}{path}", params=params, timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as exc:
        st.error(f"Couldn't reach the backend: {exc}")
        return None


def _post(path: str, json_body: dict) -> dict | None:
    try:
        resp = requests.post(f"{BACKEND_URL}{path}", json=json_body, timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as exc:
        st.error(f"Couldn't reach the backend: {exc}")
        return None


def _delete(path: str) -> bool:
    try:
        resp = requests.delete(f"{BACKEND_URL}{path}", timeout=TIMEOUT)
        resp.raise_for_status()
        return True
    except requests.exceptions.RequestException as exc:
        st.error(f"Couldn't reach the backend: {exc}")
        return False


@st.cache_data(ttl=300)
def get_clients() -> list[dict]:
    return _get("/clients") or []


@st.cache_data(ttl=300)
def get_products() -> list[dict]:
    result = _get("/products")
    return (result or {}).get("products", [])


def get_health() -> dict | None:
    return _get("/health")


def format_inr(amount: float) -> str:
    """Format a number with Indian digit grouping and a rupee sign."""
    negative = amount < 0
    amount = abs(amount)
    whole, _, frac = f"{amount:,.2f}".partition(".")
    whole = whole.replace(",", "")
    if len(whole) > 3:
        last3 = whole[-3:]
        rest = whole[:-3]
        groups = []
        while len(rest) > 2:
            groups.insert(0, rest[-2:])
            rest = rest[:-2]
        if rest:
            groups.insert(0, rest)
        whole = ",".join(groups) + "," + last3
    sign = "-" if negative else ""
    return f"{sign}₹{whole}.{frac}"


# ── Sidebar ───────────────────────────────────────────────────────────────────
#
# One chat session per client, persisted server-side (SQLite + LangGraph checkpointer),
# so switching clients or reloading the page restores prior history via the backend
# rather than relying on any client-side cache.

if "session_id" not in st.session_state:
    st.session_state.session_id = None
if "history" not in st.session_state:
    st.session_state.history = []
if "client_id" not in st.session_state:
    st.session_state.client_id = None


def _load_session(client_id: int) -> None:
    st.session_state.client_id = client_id
    st.session_state.session_id = f"client-{client_id}"
    messages = _get(f"/sessions/{st.session_state.session_id}/messages") or []
    st.session_state.history = [
        {"role": m["role"], "content": m["content"], "handled_by": m.get("handled_by")}
        for m in messages
    ]


def _select_client(client_id: int) -> None:
    st.session_state.client_selector = client_id
    _load_session(client_id)


with st.sidebar:
    st.header("Client")

    clients = get_clients()
    if clients:
        options = {c["id"]: f"{c['name']} — {c['industry']}" for c in clients}

        if st.session_state.client_id is None:
            _select_client(clients[0]["id"])

        st.selectbox(
            "Select client",
            options=list(options.keys()),
            format_func=lambda cid: options[cid],
            key="client_selector",
            on_change=lambda: _load_session(st.session_state.client_selector),
        )

        if st.button("New conversation"):
            _delete(f"/sessions/{st.session_state.session_id}")
            st.session_state.history = []
            st.rerun()

        st.divider()
        st.subheader("Sessions")
        sessions = _get("/sessions") or []
        if not sessions:
            st.caption("No conversations yet — say hello in the Chat tab.")
        for s in sessions:
            is_active = s["client_id"] == st.session_state.client_id
            label = f"{'● ' if is_active else '○ '}{s['client_name']}"
            st.button(
                label,
                key=f"session_btn_{s['session_id']}",
                use_container_width=True,
                disabled=is_active,
                on_click=_select_client,
                args=(s["client_id"],),
            )
            preview = s["last_message_preview"]
            st.caption(preview[:60] + "…" if len(preview) > 60 else preview)
    else:
        st.warning("No clients available.")

    st.divider()

    health = get_health()
    if health:
        st.caption(f"Provider: {health['provider']} · Model: {health['model']}")
    else:
        st.error("Backend unreachable.")


# ── Tabs ──────────────────────────────────────────────────────────────────────

tab_chat, tab_dashboard, tab_catalog = st.tabs(
    ["Chat with your RM", "Cashflow dashboard", "Product catalog"]
)


# ── Tab 1: Chat ─────────────────────────────────────────────────────────────

with tab_chat:
    quick_col1, quick_col2, quick_col3 = st.columns(3)
    quick_prompts = [
        (quick_col1, "Summarize my cashflow"),
        (quick_col2, "Do I have any cash gaps coming up?"),
        (quick_col3, "What products suit my business?"),
    ]
    for col, prompt in quick_prompts:
        with col:
            if st.button(prompt, use_container_width=True):
                st.session_state.pending_message = prompt

    for msg in st.session_state.history:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])
            if msg["role"] == "assistant":
                badge = AGENT_BADGES.get(msg["handled_by"], msg["handled_by"])
                st.caption(badge)

    typed_input = st.chat_input("Ask your relationship manager...")
    message = st.session_state.pop("pending_message", None) or typed_input

    if message:
        with st.chat_message("user"):
            st.write(message)
        st.session_state.history.append({"role": "user", "content": message})

        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                response = _post(
                    "/chat",
                    {
                        "session_id": st.session_state.session_id,
                        "client_id": st.session_state.client_id,
                        "message": message,
                    },
                )
            if response:
                badge = AGENT_BADGES.get(response["handled_by"], response["handled_by"])
                st.write(response["reply"])
                st.caption(badge)
                st.session_state.history.append(
                    {
                        "role": "assistant",
                        "content": response["reply"],
                        "handled_by": response["handled_by"],
                    }
                )
        # st.chat_input doesn't auto-float to the bottom when nested inside st.tabs(), so
        # without this the input box renders inline where it's called — above the new
        # exchange instead of below it. Rerunning replays the history loop with this turn
        # already included, settling the input back below all messages.
        st.rerun()


# ── Tab 2: Cashflow dashboard ────────────────────────────────────────────────

with tab_dashboard:
    if st.session_state.client_id is None:
        st.info("Select a client from the sidebar to view their dashboard.")
    else:
        months = st.radio("Months", options=[3, 6, 12], index=2, horizontal=True)

        summary = _get(f"/clients/{st.session_state.client_id}/cashflow", {"months": months})
        if summary:
            col1, col2, col3 = st.columns(3)
            col1.metric("Total inflow", format_inr(summary["total_in"]))
            col2.metric("Total outflow", format_inr(summary["total_out"]))
            col3.metric("Net", format_inr(summary["net"]))

            monthly = summary.get("monthly", [])
            if monthly:
                df = pd.DataFrame(monthly).set_index("month")[["inflow", "outflow"]]
                st.subheader("Monthly inflow vs outflow")
                st.bar_chart(df)
            else:
                st.info("No monthly data available for this period.")

        categories = _get(f"/clients/{st.session_state.client_id}/categories", {"months": months})
        if categories and categories.get("categories"):
            st.subheader("Outflow by category")
            cat_df = pd.DataFrame(categories["categories"]).set_index("category")
            st.bar_chart(cat_df, horizontal=True)

        gaps = _get(f"/clients/{st.session_state.client_id}/cash-gaps", {"months": months})
        if gaps is not None:
            st.subheader("Cash gaps")
            gap_list = gaps.get("gaps", [])
            if gap_list:
                for gap in gap_list:
                    st.warning(
                        f"**{gap['month']}** — gap of {format_inr(gap['gap'])} "
                        f"(largest cost driver: {gap['largest_category']})"
                    )
            else:
                st.success("No cash gaps detected")


# ── Tab 3: Product catalog ───────────────────────────────────────────────────

with tab_catalog:
    products = get_products()
    if not products:
        st.info("No products available.")
    else:
        for product in products:
            with st.expander(f"{product['name']} — {product['category']}"):
                st.write(product["description"])
                st.write(f"**Rate/fee:** {product['interest_rate_or_fee']}")
                if product.get("features"):
                    st.write("**Features:**")
                    for feature in product["features"]:
                        st.write(f"- {feature}")

                if st.session_state.client_id is None:
                    st.caption("Select a client from the sidebar to check eligibility.")
                elif st.button("Check my eligibility", key=f"elig_{product['id']}"):
                    result = _get(
                        f"/products/{product['id']}/eligibility",
                        {"client_id": st.session_state.client_id},
                    )
                    if result:
                        if result["eligible"]:
                            st.success(result["reason"])
                        else:
                            st.error(result["reason"])

        st.caption("Want a recommendation? Ask the RM in the Chat tab.")
