'''Live dashboard for the weather pipeline.

Run locally from the project folder:  streamlit run dashboard/app.py
'''
import os

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()  # locally: reads DATABASE_URL from .env. On Streamlit Cloud: from app secrets.

st.set_page_config(page_title='Weather Tracker', page_icon='🌦️', layout='wide')

METRICS = {
    'temperature_2m': 'Temperature (°C)',
    'apparent_temperature': 'Feels like (°C)',
    'relative_humidity_2m': 'Humidity (%)',
    'precipitation': 'Precipitation (mm)',
    'wind_speed_10m': 'Wind speed (km/h)',
    'wind_gusts_10m': 'Wind gusts (km/h)',
    'surface_pressure': 'Pressure (hPa)',
    'cloud_cover': 'Cloud cover (%)',
}


@st.cache_resource  # create the database connection pool once, reuse it on every rerun
def get_engine():
    # Tell SQLAlchemy to use psycopg2 (the same driver load.py uses).
    url = os.environ['DATABASE_URL'].replace('postgresql://', 'postgresql+psycopg2://', 1)
    return create_engine(url, pool_pre_ping=True)


@st.cache_data(ttl=600)  # re-query at most every 10 minutes
def load_data(hours):
    query = text('''
        SELECT *
        FROM weather_hourly
        WHERE observed_at >= now() - make_interval(hours => :hours)
        ORDER BY observed_at
    ''')
    with get_engine().connect() as conn:
        return pd.read_sql(query, conn, params={'hours': hours})


st.title('🌦️ Live Weather Tracker')
st.caption('Hourly readings from Open-Meteo, loaded into Postgres every hour by the pipeline.')

ranges = {'Last 24 hours': 24, 'Last 3 days': 72, 'Last 7 days': 168, 'Last 30 days': 720}
range_label = st.sidebar.radio('Time range', list(ranges), index=1)
df = load_data(ranges[range_label])

if df.empty:
    st.warning('No data yet. Run `python load.py` (or wait for the hourly job) and refresh.')
    st.stop()

cities = sorted(df['city'].unique())
chosen = st.sidebar.multiselect('Cities', cities, default=cities)
if not chosen:
    st.info('Pick at least one city in the sidebar.')
    st.stop()
df = df[df['city'].isin(chosen)]

# Pipeline health: how long since the job last wrote data?
last_load = df['loaded_at'].max()
age_min = (pd.Timestamp.now(tz='UTC') - last_load).total_seconds() / 60
status = '🟢 Up to date' if age_min < 90 else '🔴 Stale: check the hourly job'
st.sidebar.markdown(f'**Pipeline:** {status}  \nLast load {age_min:.0f} min ago')
if st.sidebar.button('Refresh now'):
    load_data.clear()
    st.rerun()

# Latest reading per city
st.subheader('Right now')
latest = df.sort_values('observed_at').groupby('city').tail(1).set_index('city')
cols = st.columns(len(chosen))
for col, city in zip(cols, chosen):
    if city not in latest.index:
        continue
    r = latest.loc[city]
    prev = df[(df['city'] == city) & (df['observed_at'] == r['observed_at'] - pd.Timedelta(hours=1))]
    delta = None if prev.empty else f"{r['temperature_2m'] - prev['temperature_2m'].iloc[0]:+.1f} °C vs 1h ago"
    with col:
        st.metric(city, f"{r['temperature_2m']:.1f} °C", delta)
        st.caption(
            f"Feels like {r['apparent_temperature']:.1f} °C · "
            f"Humidity {r['relative_humidity_2m']:.0f}% · "
            f"Wind {r['wind_speed_10m']:.0f} km/h"
        )

# Trend chart: one line per city
st.subheader('Trend')
metric = st.selectbox('Measure', list(METRICS), format_func=METRICS.get)
wide = df.pivot_table(index='observed_at', columns='city', values=metric)
st.line_chart(wide, y_label=METRICS[metric])

# Summary table for the selected range
st.subheader(f'Summary ({range_label.lower()})')
summary = df.groupby('city').agg(
    min_temp=('temperature_2m', 'min'),
    avg_temp=('temperature_2m', 'mean'),
    max_temp=('temperature_2m', 'max'),
    total_precip_mm=('precipitation', 'sum'),
    max_gust_kmh=('wind_gusts_10m', 'max'),
    hours=('observed_at', 'count'),
).round(1)
st.dataframe(summary, width='stretch')

with st.expander('Raw data'):
    st.dataframe(df.sort_values('observed_at', ascending=False), width='stretch', hide_index=True)
