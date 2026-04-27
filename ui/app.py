"""
Theia — Streamlit chat UI.

Run with:
    PYTHONPATH=. streamlit run ui/app.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import streamlit as st

from agents.orchestrator import route
from connectors.sqlite_connector import list_schemas, list_tables
from security.audit_logger import audit_stats
from security.pii_detector import mask as pii_mask
from security.audit_logger import log_interaction

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Theia — Data Intelligence",
    page_icon="🔭",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
  /* ── Fixed centred banner ─────────────────────────────────────────────── */
  .theia-banner {
    position: fixed;
    top: 2.875rem;          /* sits below Streamlit's native toolbar (~46 px) */
    left: 0; right: 0;
    z-index: 999;
    background: linear-gradient(135deg, #07111f 0%, #0f1f38 100%);
    border-bottom: 1px solid #1e3a5f;
    padding: 0.65rem 1rem;
    text-align: center;
  }
  .theia-banner .t-name {
    font-size: 2rem;
    font-weight: 900;
    letter-spacing: 0.25em;
    color: #4A90D9;
    text-shadow: 0 0 18px rgba(74,144,217,0.55), 0 0 40px rgba(74,144,217,0.25);
    font-family: 'Segoe UI', 'Helvetica Neue', Arial, sans-serif;
    line-height: 1.1;
  }
  .theia-banner .t-sub {
    font-size: 0.65rem;
    color: #6fa8dc;
    letter-spacing: 0.35em;
    opacity: 0.7;
    margin-top: 0.1rem;
    font-family: 'Segoe UI', Arial, sans-serif;
  }
  /* Push main content below the banner */
  section.main .block-container { padding-top: 7rem !important; }

  /* ── Other UI elements ────────────────────────────────────────────────── */
  .source-tag { display:inline-block; background:#1e3a5f; color:#7eb8f7;
                border-radius:4px; padding:2px 8px; font-size:0.78rem; margin:2px 2px 0 0; }
  .pii-badge  { background:#5a1e1e; color:#f7a07e;
                border-radius:4px; padding:2px 8px; font-size:0.78rem; }
  .row-note   { font-size:0.80rem; color:#888; margin-top:4px; }
</style>

<div class="theia-banner">
  <div class="t-name">🔭 &nbsp; Ｔ Ｈ Ｅ Ｉ Ａ</div>
  <div class="t-sub">DATA INTELLIGENCE ASSISTANT &nbsp;·&nbsp; 100 % LOCAL</div>
</div>
""", unsafe_allow_html=True)


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 🔭 Theia")
    st.caption("AI Data Intelligence Assistant")
    st.divider()

    st.markdown("**Data Landscape**")
    for schema in list_schemas():
        tables = list_tables(schema)
        with st.expander(f"`{schema}` — {len(tables)} tables"):
            for t in tables:
                st.markdown(f"• {t}")

    st.divider()
    st.markdown("**Session Stats**")
    try:
        stats = audit_stats()
        c1, c2 = st.columns(2)
        c1.metric("Questions", stats["total_questions"])
        c2.metric("PII masked", stats["pii_detected"])
        st.caption(f"Avg response: {stats['avg_response_ms']:,} ms")
    except Exception:
        st.caption("No interactions yet.")

    st.divider()
    if st.button("🔄 Check for schema changes", use_container_width=True):
        with st.spinner("Checking…"):
            from learning.reindexer import reindex_changed
            summary = reindex_changed(verbose=False)
        if summary["reindexed"] == 0 and summary["checked"] == 0:
            st.success("No changes detected.")
        else:
            st.success(f"Re-indexed {summary['reindexed']} table(s).")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _render_result(result: dict) -> None:
    """Render Theia's answer — narrative + optional table + optional chart."""

    # 1. Always show the narrative text
    st.markdown(result["answer"])

    # 2. Column / table metadata → clean dataframe
    if result.get("meta_table"):
        df = pd.DataFrame(result["meta_table"])
        st.dataframe(df, use_container_width=True, hide_index=True)

    # 3. Data rows → dataframe + optional chart
    rows = result.get("rows")
    if rows:
        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True, hide_index=True)

        total = result.get("total_rows", len(rows))
        from agents.sql_agent import MAX_DISPLAY_ROWS
        if total > MAX_DISPLAY_ROWS:
            st.markdown(
                f'<div class="row-note">Showing {len(rows)} of {total} rows.</div>',
                unsafe_allow_html=True,
            )

        # Chart — only when data shape supports it
        chart_type = result.get("chart_type")
        if chart_type and len(df.columns) >= 2:
            label_col = df.columns[0]
            numeric_cols = [c for c in df.columns[1:] if pd.api.types.is_numeric_dtype(df[c])]
            if numeric_cols:
                chart_df = df.set_index(label_col)[numeric_cols]
                st.divider()
                if chart_type == "line":
                    st.line_chart(chart_df)
                else:
                    st.bar_chart(chart_df)

    # 4. Source citations
    sources = result.get("sources") or []
    if sources:
        tags = "".join(f'<span class="source-tag">{s}</span>' for s in sources)
        st.markdown(f"**Sources:** {tags}", unsafe_allow_html=True)

    # 5. PII badge
    if result.get("pii_masked"):
        st.markdown('<span class="pii-badge">⚠ PII detected and masked</span>',
                    unsafe_allow_html=True)


# ── Chat area ─────────────────────────────────────────────────────────────────

if "messages" not in st.session_state:
    st.session_state.messages = []
    st.session_state.messages.append({
        "role": "assistant",
        "result": {
            "answer": (
                "Hello. I'm Theia — I have complete knowledge of your data landscape across "
                "four schemas: **music** (Chinook), **sales** (Northwind), **rental** (Sakila), "
                "and **geography** (World).\n\n"
                "Try asking me:\n"
                "- *Show me the top 10 customers by total orders*\n"
                "- *What columns are in the Orders table?*\n"
                "- *What tables are in the music schema?*\n"
                "- *Profile the Invoice table*"
            ),
            "intent": "greeting", "sources": [],
            "rows": None, "columns": None,
            "chart_type": None, "meta_table": None, "pii_masked": False,
        },
    })

# Render history
for msg in st.session_state.messages:
    avatar = "🔭" if msg["role"] == "assistant" else "👤"
    with st.chat_message(msg["role"], avatar=avatar):
        _render_result(msg["result"])

# Input
if prompt := st.chat_input("Ask Theia about your data…"):
    user_result = {
        "answer": prompt, "intent": "user", "sources": [],
        "rows": None, "columns": None, "chart_type": None,
        "meta_table": None, "pii_masked": False,
    }
    st.session_state.messages.append({"role": "user", "result": user_result})
    with st.chat_message("user", avatar="👤"):
        st.markdown(prompt)

    with st.chat_message("assistant", avatar="🔭"):
        with st.spinner("Theia is thinking…"):
            import time
            start = time.monotonic()
            masked_q, pii_found = pii_mask(prompt)

            # Build conversation history so Theia can resolve follow-up questions
            history = []
            for msg in st.session_state.messages:
                if msg["role"] == "user":
                    history.append({"role": "user", "content": msg["result"]["answer"]})
                elif msg["role"] == "assistant" and msg["result"].get("intent") != "greeting":
                    history.append({"role": "assistant", "content": msg["result"]["answer"][:500]})

            result = route(masked_q, history=history[-8:])  # last 4 exchanges
            result["pii_masked"] = pii_found
            duration_ms = int((time.monotonic() - start) * 1000)

            log_interaction(
                question=prompt,
                answer=result["answer"],
                intent=result["intent"],
                sources=result.get("sources") or [],
                pii_masked=pii_found,
                duration_ms=duration_ms,
            )

        _render_result(result)

    st.session_state.messages.append({"role": "assistant", "result": result})
    st.rerun()
