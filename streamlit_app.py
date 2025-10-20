import streamlit as st
import pandas as pd
from pathlib import Path

# ---- PAGE SETUP ----
st.set_page_config(page_title="News Agent", page_icon="🗞️", layout="wide")

st.title("🗞️ News Agent")
st.write("Deployment check: If you can see this message, your app is running successfully!")

# ---- DISPLAY RESULTS ----
results_csv = Path("results.csv")

if results_csv.exists():
    st.subheader("Existing results.csv")
    df = pd.read_csv(results_csv)
    st.dataframe(df, width="stretch")
else:
    st.info("Upload a CSV to preview, or generate results locally and push results.csv.")

    uploaded = st.file_uploader("Upload a CSV file", type=["csv"])
    if uploaded is not None:
        try:
            df = pd.read_csv(uploaded)
            st.success("File uploaded successfully!")
            st.dataframe(df, width="stretch")
        except Exception as e:
            st.error(f"Error reading CSV file: {e}")

# ---- FOOTER ----
st.markdown("---")
st.caption("Built with ❤️ using Streamlit | © 2025 News Agent")
