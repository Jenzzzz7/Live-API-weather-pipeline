'''Create the weather_hourly table in your database. Run once: python setup_db.py'''
import os
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

load_dotenv()

sql = (Path(__file__).parent / 'schema.sql').read_text(encoding='utf-8')

conn = psycopg2.connect(os.environ['DATABASE_URL'])
try:
    with conn, conn.cursor() as cur:
        cur.execute(sql)
finally:
    conn.close()

print('weather_hourly table is ready.')
