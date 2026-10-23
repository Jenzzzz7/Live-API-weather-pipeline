# Live Weather Pipeline

An hourly ETL pipeline that pulls live weather for Halifax, Toronto and Vancouver from the
[Open-Meteo API](https://open-meteo.com/), stores it in a Postgres database (Neon), and shows
it on a Streamlit dashboard.

```
Open-Meteo API ──► extract.py ──► load.py ──► Postgres (Neon) ──► dashboard/app.py
                     (pandas)     (upsert)    weather_hourly        (Streamlit)
                         ▲
        GitHub Actions runs this every hour
```

## What each file does

| File | Job |
|---|---|
| `extract.py` | Calls Open-Meteo for each city, builds a pandas DataFrame of hourly readings (last 2 days), drops future forecast hours. |
| `load.py` | Runs the extract, then **upserts** rows into `weather_hourly`: new hours are inserted, existing hours are updated, so re-runs never create duplicates. |
| `schema.sql` | Defines the `weather_hourly` table. `(city, observed_at)` is the primary key. |
| `setup_db.py` | Runs `schema.sql` against your database. Safe to run any number of times. |
| `.github/workflows/pipeline.yml` | Runs `setup_db.py` + `load.py` on GitHub's servers every hour at :07 UTC. |
| `dashboard/app.py` | Streamlit dashboard: current conditions, trend chart, summary table, pipeline freshness. |

## Measurements collected

Temperature, feels-like temperature, relative humidity, precipitation, wind speed, wind gusts,
surface pressure and cloud cover, one value per city per hour (UTC).

## Run it locally (Windows)

```powershell
cd Desktop\weather-pipeline
.venv\Scripts\activate
pip install -r requirements.txt

# .env must contain:  DATABASE_URL=postgresql://...your Neon connection string...
python setup_db.py      # create the table (once)
python load.py          # fetch + load; run it again to see the count stay the same

pip install -r dashboard\requirements.txt
streamlit run dashboard\app.py
```

## Run it every hour (GitHub Actions)

1. Push this folder to a GitHub repo (`.env` and `.venv` are git-ignored, so your password stays local).
2. Repo → **Settings → Secrets and variables → Actions → New repository secret**:
   name `DATABASE_URL`, value = your Neon connection string.
3. Repo → **Actions → Weather pipeline → Run workflow** to test it once. After that it runs hourly.

Note: GitHub pauses scheduled workflows in repos with no activity for 60 days. Re-enable from the Actions tab.

## Deploy the dashboard (Streamlit Community Cloud)

1. Sign in at share.streamlit.io with GitHub → **Create app** → pick this repo, main file `dashboard/app.py`.
2. Under **Advanced settings → Secrets** add:
   ```toml
   DATABASE_URL = "postgresql://...your Neon connection string..."
   ```

## Design decisions

- **Upsert instead of insert.** Each run re-fetches the last 48 hours, so a missed run fills itself in on the next one, and Open-Meteo's revised values overwrite older ones.
- **UTC everywhere.** Timestamps are stored as `TIMESTAMPTZ` in UTC to avoid daylight-saving bugs across three time zones.
- **Secrets in environment variables.** The connection string lives in `.env` locally, a GitHub secret in CI, and Streamlit secrets in the cloud. It is never committed.
- **Pinned dependencies** so the hourly job installs exactly what was tested.

## Ideas for next steps

- Add more cities (just add them to `CITIES` in `extract.py`)
- Daily aggregate table/view (min, max, total rain per city per day)
- Alerts (e.g. email when gusts exceed 70 km/h)
- Data quality checks (missing hours, impossible values)
