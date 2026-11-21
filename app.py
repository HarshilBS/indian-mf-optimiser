import streamlit as st
import pandas as pd
import numpy as np
from mftool import Mftool
from datetime import datetime, timedelta, date
import pulp
import plotly.express as px
import plotly.graph_objects as go
import warnings
warnings.filterwarnings('ignore')

st.set_page_config(
    page_title="Indian Mutual Fund Optimiser",
    page_icon="📈",
    layout="wide",
)

st.title("📈 Indian Mutual Fund Optimiser")
st.markdown("""
Find the **best-performing mutual funds** or analyse your portfolio between any two dates.  
Uses your classification data + live NAV from AMFI (via mftool / mfapi.in).

*Past performance is not indicative of future returns. Not investment advice.*
""")

# Full version is available locally; this is a minimal fix. See artifacts for complete app.
print('App updated - full version pending large content push')
