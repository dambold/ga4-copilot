import traceback
import os, json
import pandas as pd
import plotly.express as px
from datetime import date, timedelta
from dotenv import load_dotenv
import streamlit as st
from openai import OpenAI

from ga import run_ga_report, default_dates, MOCK_MODE
from prompts import SYSTEM_PROMPT, TRANSLATE_PROMPT

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

st.set_page_config(page_title="GA4 Insights Copilot", page_icon="📈", layout="wide")

st.title("GA4 Insights Copilot")
st.caption("Ask natural-language questions about your GA4 data and see instant tables and charts.")

# ---------------- Sidebar ----------------
with st.sidebar:
    st.subheader("Settings")
    mock = st.toggle("Mock Mode (CSV)", value=MOCK_MODE)

    today = date.today()
    presets = {
        "Last 7 days":  (today - timedelta(days=7),  today),
        "Last 28 days": (today - timedelta(days=28), today),
        "Last 90 days": (today - timedelta(days=90), today),
    }
    choice = st.selectbox("Date preset", list(presets.keys()), index=1)

    st.divider()
    if st.button("Test LLM connectivity"):
        try:
            key = (st.secrets.get("OPENAI_API_KEY", None) if hasattr(st, "secrets") else None) or os.getenv("OPENAI_API_KEY", "")
            key = (key or "").strip()
            if not key:
                st.error("No OPENAI_API_KEY found in Streamlit secrets or environment.")
            else:
                client = OpenAI(api_key=key)
                pong = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": "Say 'pong'"}],
                    temperature=0.0,
                )
                st.success(f"LLM OK: {pong.choices[0].message.content!r}")
        except Exception as e:
            st.error(f"LLM error: {e}")
            st.caption("See deployment logs for stack trace.")
            traceback.print_exc()

# ---------------- Main controls ----------------
question = st.text_input("Ask a question", placeholder="e.g. Top landing pages by users last 7 days")
go = st.button("Run")

def openai_parse_query(q: str) -> dict:
    """Use OpenAI to turn a plain-English question into a GA4 query spec."""
    # Prefer Streamlit secrets on cloud; fall back to env locally
    key = (st.secrets.get("OPENAI_API_KEY", None) if hasattr(st, "secrets") else None) or os.getenv("OPENAI_API_KEY", "")
    key = (key or "").strip()

    # Date helpers (includes d1)
    today = date.today()
    d0  = today.isoformat()
    d1  = (today - timedelta(days=1)).isoformat()
    d7  = (today - timedelta(days=7)).isoformat()
    d30 = (today - timedelta(days=30)).isoformat()

    # No key? Return a safe default (works in mock mode)
    if not key:
        return {
            "dimensions": ["landingPagePlusQueryString"],
            "metrics": ["totalUsers"],
            "date_range": {"start_date": d7, "end_date": d0},
            "filters": ""
        }

    prompt = TRANSLATE_PROMPT.format(question=q, d0=d0, d1=d1, d7=d7, d30=d30)
    msgs = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": prompt}
    ]

    try:
        client = OpenAI(api_key=key)
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=msgs,
            temperature=0.1,
        )
        text = (resp.choices[0].message.content or "").strip()
        if text.startswith("```"):
            text = text.strip("`").replace("json", "").strip()
        return json.loads(text)
    except Exception:
        st.info("Using fallback query (OpenAI unavailable). Check Secrets.")
        return {
            "dimensions": ["landingPagePlusQueryString"],
            "metrics": ["totalUsers"],
            "date_range": {"start_date": d7, "end_date": d0},
            "filters": ""
        }

def render(df: pd.DataFrame, dims, mets):
    if df.empty:
        st.warning("No data returned.")
        return
    st.subheader("Results")
    st.dataframe(df, use_container_width=True, hide_index=True)

    if len(dims) >= 1 and len(mets) >= 1:
        x, y = dims[0], mets[0]
        if x in df.columns and y in df.columns:
            fig = px.bar(df.sort_values(y, ascending=False).head(20), x=x, y=y)
            st.plotly_chart(fig, use_container_width=True)

if go and question.strip():
    with st.spinner("Thinking..."):
        query = openai_parse_query(question)

        # Apply chosen preset if the LLM didn’t specify dates
        if not query.get("date_range") or not query["date_range"].get("start_date"):
            s, e = presets[choice]
            query["date_range"] = {"start_date": s.isoformat(), "end_date": e.isoformat()}

        df = run_ga_report(query)
        render(df, query.get("dimensions", []), query.get("metrics", []))

st.divider()
st.caption("Tech: GA4 API · OpenAI · Streamlit · Plotly")
