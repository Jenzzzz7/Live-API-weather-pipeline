import os

import pandas as pd
import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import execute_values

from extract import CITIES, fetch_weather

load_dotenv()  # reads DATABASE_URL from your .env file

COLUMNS = [
    'city', 'observed_at', 'temperature_2m', 'apparent_temperature',
    'relative_humidity_2m', 'precipitation', 'wind_speed_10m',
    'wind_gusts_10m', 'surface_pressure', 'cloud_cover',
]
KEY_COLUMNS = ['city', 'observed_at']
VALUE_COLUMNS = [c for c in COLUMNS if c not in KEY_COLUMNS]

column_list = ', '.join(COLUMNS)
update_list = ', '.join(f'{c} = EXCLUDED.{c}' for c in VALUE_COLUMNS)

# Insert new rows. If (city, observed_at) already exists, update that row instead.
UPSERT_SQL = f'''
INSERT INTO weather_hourly ({column_list})
VALUES %s
ON CONFLICT (city, observed_at) DO UPDATE SET
    {update_list},
    loaded_at = now()
'''


def to_rows(df):
    '''Convert a DataFrame to plain Python tuples (NaN becomes NULL).'''
    rows = []
    for rec in df[COLUMNS].itertuples(index=False):
        row = [rec[0], rec[1].to_pydatetime()]
        row += [None if pd.isna(v) else float(v) for v in rec[2:]]
        rows.append(tuple(row))
    return rows


if __name__ == '__main__':
    frames = [fetch_weather(city, lat, lon) for city, (lat, lon) in CITIES.items()]
    weather = pd.concat(frames, ignore_index=True)
    rows = to_rows(weather)

    conn = psycopg2.connect(os.environ['DATABASE_URL'])
    try:
        with conn, conn.cursor() as cur:  # commits on success, rolls back on error
            execute_values(cur, UPSERT_SQL, rows)
            cur.execute('SELECT COUNT(*) FROM weather_hourly')
            total = cur.fetchone()[0]
    finally:
        conn.close()

    print(f'Sent {len(rows)} rows. Table now holds {total} rows.')