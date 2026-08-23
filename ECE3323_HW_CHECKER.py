"""
EMAG2 (ECE3323) homework checker -- Streamlit front end.

Reads the flat widget table written by hw_checker_generator.py from the
Google Sheet, lets the student pick a homework / question / version, then
dynamically renders the right widgets and grades them against the stored
answer ranges/values.

Expects a service account with read access to the sheet. Works either with
Streamlit secrets (for Streamlit Community Cloud) or a local
credentials.json (for running on your own machine).
"""

import json

import gspread
import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

SHEET_NAME = "ECE3323_HW_Checker"
WORKSHEET_INDEX = 0
CACHE_TTL_SECONDS = 60


# ----------------------------------------------------------------------
# Data loading
# ----------------------------------------------------------------------

@st.cache_resource
def get_client():
    # Accessing st.secrets at all raises when no secrets.toml exists, so this
    # has to be try/except rather than a plain `in` check -- that's what was
    # blowing up with "No secrets found" even though credentials.json is right there.
    try:
        has_secret = "gcp_service_account" in st.secrets
    except Exception:
        has_secret = False

    if has_secret:
        return gspread.service_account_from_dict(st.secrets["gcp_service_account"])
    return gspread.service_account(filename=".gitignore\\credentials.json")


@st.cache_data(ttl=CACHE_TTL_SECONDS)
def load_data():
    gc = get_client()
    sheet = gc.open(SHEET_NAME)
    worksheet = sheet.get_worksheet(WORKSHEET_INDEX)
    records = worksheet.get_all_records()
    df = pd.DataFrame(records)
    # numeric columns come back as strings for blank cells -- coerce
    for col in ("hw", "question", "order", "answer_low", "answer_high"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


# ----------------------------------------------------------------------
# Widget rendering + grading
# ----------------------------------------------------------------------

def widget_key(hw, question, version, part, objectname):
    return f"{hw}_{question}_{version}_{part}_{objectname}"


def render_widget(hw, question, version, part, row):
    key = widget_key(hw, question, version, part, row["objectname"])
    unit_suffix = f" ({row['unit']})" if row["unit"] else ""

    if row["widget_type"] == "text_input" and row["input_type"] == "numerical":
        value = st.number_input(f"{row['label']}{unit_suffix}", key=key, value=None,
                                 format="%.6g", step=None)
        return key, row, value

    if row["widget_type"] == "selectbox":
        options = json.loads(row["options"]) if row["options"] else []
        value = st.selectbox(f"{row['label']}{unit_suffix}", options, key=key,
                              index=None, placeholder="Select...")
        return key, row, value

    # fallback: plain text input for anything untyped
    value = st.text_input(f"{row['label']}{unit_suffix}", key=key)
    return key, row, value


def grade(row, value):
    """Returns (is_correct, reason_if_missing)."""
    if value is None or value == "":
        return None, "no answer given"

    if row["widget_type"] == "text_input" and row["input_type"] == "numerical":
        lo, hi = row["answer_low"], row["answer_high"]
        if pd.isna(lo) or pd.isna(hi):
            return None, "no answer range on record"
        return (lo <= float(value) <= hi), None

    if row["widget_type"] == "selectbox":
        accepted = json.loads(row["answer"]) if row["answer"] else []
        return (value in accepted), None

    return None, "no grading rule for this widget type"


# ----------------------------------------------------------------------
# App
# ----------------------------------------------------------------------

st.set_page_config(page_title="ECE3323 Homework Checker", layout="centered")
st.title("ECE3323 Homework Checker")

# Forces a rerun every 60s so the cached sheet data (ttl=CACHE_TTL_SECONDS)
# gets picked up automatically even if the student isn't clicking anything.
st_autorefresh(interval=CACHE_TTL_SECONDS * 1000, key="sheet_autorefresh")

try:
    df = load_data()
except Exception as e:
    st.error(f"Couldn't load the answer sheet: {e}")
    st.stop()

if df.empty:
    st.warning("The answer sheet is empty.")
    st.stop()

# --- selectors -----------------------------------------------------
hw_options = sorted(df["hw"].dropna().unique())
hw = st.selectbox("Homework", hw_options, format_func=lambda x: f"HW{int(x)}")

q_options = sorted(df.loc[df["hw"] == hw, "question"].dropna().unique())
question = st.selectbox("Question", q_options, format_func=lambda x: f"Q{int(x)}")

v_options = sorted(df.loc[(df["hw"] == hw) & (df["question"] == question), "version"].unique())
version = st.selectbox("Version", v_options)

subset = df[(df["hw"] == hw) & (df["question"] == question) & (df["version"] == version)]

st.divider()

# --- render widgets, grouped by part, in order ----------------------
rendered = []  # list of (key, row) for grading after submit
for part, part_df in subset.groupby("part", sort=False):
    if part != "main":
        st.subheader(f"Part {part}")
    for _, row in part_df.sort_values("order").iterrows():
        key, row, value = render_widget(hw, question, version, part, row)
        rendered.append((key, row))

st.divider()

if st.button("Check My Answers", type="primary"):
    n_correct = 0
    n_gradeable = 0
    for key, row in rendered:
        value = st.session_state.get(key)
        is_correct, reason = grade(row, value)
        if is_correct is None:
            st.info(f"**{row['label']}** -- {reason}")
            continue
        n_gradeable += 1
        if is_correct:
            n_correct += 1
            st.success(f"**{row['label']}** -- correct")
        else:
            st.error(f"**{row['label']}** -- not quite, try again")

    if n_gradeable:
        st.metric("Score", f"{n_correct}/{n_gradeable}")