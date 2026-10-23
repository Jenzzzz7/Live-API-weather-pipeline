# 🌦️ Live API Weather Pipeline

![Pipeline status](https://github.com/Jenzzzz7/Live-API-weather-pipeline/actions/workflows/pipeline.yml/badge.svg)
![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-Neon-4169E1?logo=postgresql&logoColor=white)
![Streamlit](https://img.shields.io/badge/Dashboard-Streamlit-FF4B4B?logo=streamlit&logoColor=white)
![GitHub Actions](https://img.shields.io/badge/Scheduled-GitHub%20Actions-2088FF?logo=githubactions&logoColor=white)

An automated **ETL (Extract → Transform → Load) pipeline** that collects live hourly weather
data for **Halifax, Toronto and Vancouver** from the free [Open-Meteo API](https://open-meteo.com/).
It stores the data in a cloud **PostgreSQL** database (Neon) and presents it on an interactive
**Streamlit** dashboard. The pipeline runs by itself every hour on **GitHub Actions**, with no
server or laptop needing to stay on.

📄 **Full write-up:** [Project Report (PDF)](docs/Project_Report.pdf)

---

## Contents

1. [What it does](#what-it-does)
2. [Architecture](#architecture)
3. [How the pipeline works, step by step](#how-the-pipeline-works-step-by-step)
4. [Database design](#database-design)
5. [Automation and self-healing](#automation-and-self-healing)
6. [The dashboard](#the-dashboard)
7. [Project structure](#project-structure)
8. [Run it yourself](#run-it-yourself)
9. [Configuration](#configuration)
10. [Design decisions](#design-decisions)
11. [Troubleshooting](#troubleshooting)
12. [What I learned](#what-i-learned)
13. [Roadmap](#roadmap)
14. [Author](#author)

---

## What it does

| | |
|---|---|
| **Source** | Open-Meteo forecast API (free, no API key) |
| **Cities** | Halifax, Toronto, Vancouver (easy to add more) |
| **Measurements** | Temperature, feels-like temperature, humidity, precipitation, wind speed, wind gusts, surface pressure, cloud cover |
| **Granularity** | One reading per city per hour, stored in UTC |
| **Frequency** | Every hour at :07 UTC, via GitHub Actions |
| **Storage** | PostgreSQL on Neon (serverless, free tier) |
| **Output** | Streamlit dashboard with live KPIs, trend charts, summary stats and a pipeline-health indicator |

---

## Architecture

![System architecture](docs/images/architecture.png)

The project follows the classic **ETL** pattern used in data engineering:

- **Extract:** request raw data from an external source (the weather API).
- **Transform:** clean and reshape it into a consistent, tabular format.
- **Load:** write it into a database where it can be queried.

A **scheduler** (GitHub Actions) repeats the process every hour, and a **dashboard** reads from
the database to visualise the results. Each part is a separate file with one job, so each can be
tested and changed on its own.

---

## How the pipeline works, step by step

### 1. Extract: `extract.py`

1. A dictionary `CITIES` maps each city name to its latitude and longitude.
2. A list `VARIABLES` names the eight hourly measurements to request.
3. For each city, `fetch_weather()` calls the Open-Meteo API with:
   - `past_days=2` and `forecast_days=1`, so the response covers the last 48 hours plus today
   - `timezone='UTC'`, so every timestamp shares one reference clock
4. The HTTP session is wrapped with `retry(...)`. If the request fails because of a network
   blip or a rate limit, it automatically retries up to 5 times with an increasing delay
   (*exponential backoff*).
5. Open-Meteo returns data in a compact binary format (FlatBuffers). The
   `openmeteo_requests` client decodes it into arrays of numbers.

### 2. Transform (inside `extract.py`)

1. **Build the time column.** The API returns a start time, an end time and an interval rather
   than a list of timestamps. `pd.date_range(...)` rebuilds the full list of hourly timestamps.
2. **Map values to columns by position.** Each variable is read with `hourly.Variables(i)` in
   the same order as `VARIABLES`, so values can never end up in the wrong column.
3. **Add the city column**, so all three cities can be stacked into one table.
4. **Drop future hours.** The response includes forecast hours later today, and this is a
   *tracking* system. Rows where `observed_at` is after the current time are filtered out.

The output is a pandas **DataFrame**: one row per city per hour, one column per measurement.

### 3. Load: `load.py`

1. Runs the extract for every city and combines the results with `pd.concat`.
2. `to_rows()` converts the DataFrame into plain Python tuples, the format the database driver
   expects. Missing values (`NaN` in pandas) become `None`, which Postgres stores as `NULL`.
3. Connects to Postgres using `DATABASE_URL`, loaded from the `.env` file or a secret.
   The password is never written in the code.
4. Sends all rows in **one batch** with `execute_values`, which is much faster than one
   `INSERT` per row.
5. Uses an **upsert** (`INSERT ... ON CONFLICT DO UPDATE`). The next diagram explains it.
6. Everything runs inside one **transaction** (`with conn:`). Either all rows are saved or,
   if anything fails, none are, so the table is never left half-updated.

![Upsert explained](docs/images/upsert.png)

**Why upsert?** Every run re-fetches the last 48 hours, so most rows already exist. A plain
`INSERT` would either crash on the duplicate key or create duplicate rows. With the upsert:

- a new hour gets **inserted**
- an hour that's already stored gets **updated** with the latest values, since the weather
  service sometimes revises recent readings

This makes the load **idempotent**: running it once or a hundred times leaves the database in
the same state. That's what makes automatic retries and re-runs safe.

---

## Database design

![Database schema](docs/images/schema.png)

Defined in [`schema.sql`](schema.sql) and created by [`setup_db.py`](setup_db.py).

- **Composite primary key `(city, observed_at)`.** This guarantees one row per city per hour,
  and it's the rule the upsert's `ON CONFLICT` checks against.
- **`TIMESTAMPTZ` (timestamp with time zone).** All times are stored in UTC. Three cities span
  three time zones and daylight-saving changes, and UTC avoids all those bugs. The dashboard
  converts times for display.
- **`REAL` columns** for measurements. 4-byte floats are plenty for weather precision.
- **`loaded_at` audit column.** Records when the pipeline last wrote each row. The dashboard
  uses it to check whether the pipeline is healthy.
- **Index on `observed_at DESC`.** Makes "most recent readings" queries fast as the table grows.
- **`IF NOT EXISTS`.** The setup script is safe to run any number of times, which is why the
  hourly job can run it on every run.

---

## Automation and self-healing

![Hourly schedule](docs/images/schedule.png)

[`.github/workflows/pipeline.yml`](.github/workflows/pipeline.yml) tells GitHub Actions to:

1. start a fresh Ubuntu machine every hour at **:07 UTC** (`cron: '7 * * * *'`), leaving the
   API a few minutes to publish the latest hour
2. check out the code, install Python 3.11 and the pinned dependencies
3. run `setup_db.py`, which creates the table only if it's missing
4. run `load.py`, which does the extract and the upsert

The database connection string is stored as an **encrypted repository secret**
(`DATABASE_URL`), injected only at run time. It never appears in the code or the logs.

**Self-healing:** each run covers 48 hours, so consecutive runs overlap heavily. If one run
fails, for example because of an API outage, the next successful run back-fills the missing
hours automatically. No manual repair is needed for gaps shorter than two days.

You can also start a run manually from the **Actions** tab (`workflow_dispatch`).

---

## The dashboard

![Dashboard](docs/images/dashboard.png)
*Screenshot shown with sample data.*

[`dashboard/app.py`](dashboard/app.py) is a Streamlit web app that queries the database and shows:

| Section | What it shows |
|---|---|
| **Right now** | Latest temperature per city, change versus one hour earlier, feels-like, humidity and wind |
| **Trend** | Line chart of any measurement over time, one line per city |
| **Summary** | Min, average and max temperature, total precipitation, strongest gust and hours recorded |
| **Raw data** | The full table for the selected period |
| **Pipeline health** (sidebar) | 🟢 if the last load was under 90 minutes ago, 🔴 if the hourly job has stopped |

Performance details:
- `@st.cache_resource` creates the database connection pool once and reuses it.
- `@st.cache_data(ttl=600)` caches query results for 10 minutes, so clicking around doesn't
  query the database every time. **Refresh now** clears the cache on demand.
- The query uses a parameter (`:hours`) instead of building SQL from strings, which prevents
  SQL injection.

---

## Project structure

```
Live-API-weather-pipeline/
├── .github/
│   └── workflows/
│       └── pipeline.yml      # hourly GitHub Actions job
├── dashboard/
│   ├── app.py                # Streamlit dashboard
│   └── requirements.txt      # dashboard dependencies
├── docs/
│   ├── images/               # diagrams and screenshot used in this README
│   └── Project_Report.pdf    # full project report
├── extract.py                # E + T: fetch and shape weather data
├── load.py                   # L: upsert into Postgres
├── schema.sql                # table definition
├── setup_db.py               # creates the table
├── requirements.txt          # pipeline dependencies (pinned)
├── .gitignore                # keeps .env and .venv out of Git
└── .env                      # DATABASE_URL (local only, never committed)
```

---

## Run it yourself

### Prerequisites
- Python 3.11+
- A free PostgreSQL database, for example [Neon](https://neon.tech). Copy its connection string.

### 1. Clone and install

```powershell
git clone https://github.com/Jenzzzz7/Live-API-weather-pipeline.git
cd Live-API-weather-pipeline
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Add your database connection

Create a file called `.env` in the project folder:

```
DATABASE_URL=postgresql://user:password@host/dbname?sslmode=require
```

### 3. Create the table and load data

```powershell
python setup_db.py      # -> weather_hourly table is ready.
python load.py          # -> Sent N rows. Table now holds N rows.
python load.py          # run again: the total stays the same (upsert at work)
```

To preview the extract without touching the database:

```powershell
python extract.py
```

### 4. Launch the dashboard

```powershell
pip install -r dashboard\requirements.txt
streamlit run dashboard\app.py
```

### 5. Automate it with GitHub Actions

1. Push the repo to GitHub.
2. Go to **Settings → Secrets and variables → Actions → New repository secret**, name it
   `DATABASE_URL`, and paste your connection string as the value.
3. Go to **Actions → Weather pipeline → Run workflow** to test it. After that it runs hourly.

> GitHub pauses scheduled workflows in repositories with no activity for 60 days.
> Re-enable it from the Actions tab if that happens.

### 6. (Optional) Put the dashboard online

1. Sign in at [share.streamlit.io](https://share.streamlit.io) with GitHub → **Create app**.
2. Pick this repo, with main file `dashboard/app.py`.
3. Under **Advanced settings → Secrets**, add:
   ```toml
   DATABASE_URL = "postgresql://...your connection string..."
   ```

---

## Configuration

| What | Where | How |
|---|---|---|
| Add or remove cities | `extract.py` → `CITIES` | Add `'Montreal': (45.50, -73.57),` |
| Add measurements | `extract.py` → `VARIABLES`, plus `load.py` → `COLUMNS`, plus `schema.sql` | Use any [Open-Meteo hourly variable](https://open-meteo.com/en/docs) |
| History window per run | `extract.py` → `past_days` | Larger = more self-healing, slightly slower |
| Schedule | `.github/workflows/pipeline.yml` → `cron` | e.g. `'7 */3 * * *'` for every 3 hours |
| Dashboard cache time | `dashboard/app.py` → `ttl=600` | Seconds |

---

## Design decisions

| Decision | Why |
|---|---|
| **Upsert instead of insert** | Makes runs idempotent, and lets overlapping windows back-fill gaps and pick up revised values. |
| **UTC everywhere** | Avoids time-zone and daylight-saving bugs across three cities. |
| **48-hour window per run** | Overlap gives automatic recovery from failed runs. |
| **One transaction per load** | All-or-nothing writes, so the table is never half-updated. |
| **Batch insert (`execute_values`)** | One round-trip to the database instead of ~150. |
| **Secrets in environment variables** | `.env` locally, GitHub secret in CI, Streamlit secrets in the cloud. Nothing sensitive is committed. |
| **Pinned dependency versions** | The hourly job installs exactly what was tested, so an upstream release can't break it overnight. |
| **GitHub Actions for scheduling** | Free, runs in the cloud, keeps a log of every run, no server to maintain. |
| **Serverless Postgres (Neon)** | Free tier, standard SQL, reachable from GitHub Actions and Streamlit Cloud. |

---

## Troubleshooting

| Problem | Likely cause and fix |
|---|---|
| `relation "weather_hourly" does not exist` | Table not created yet. Run `python setup_db.py`. |
| `KeyError: 'DATABASE_URL'` | `.env` is missing, or it's not in the folder you're running from. |
| `there is no unique or exclusion constraint matching the ON CONFLICT` | The table was created without the primary key. Recreate it from `schema.sql`. |
| GitHub Action fails at the load step | Check the `DATABASE_URL` secret is set and spelled exactly like that. |
| Dashboard shows 🔴 Stale | The hourly job has stopped. Check the Actions tab for failed or disabled runs. |
| `No module named 'psycopg'` in the dashboard | Run `pip install -r dashboard/requirements.txt`. The app is set to use psycopg2. |

---

## What I learned

- Designing an **end-to-end ETL pipeline**, from API to database to dashboard
- Working with a **REST API** and its response format, with retries and backoff
- **Data transformation** with pandas: building time series and handling missing values
- **Relational modelling**: composite primary keys, data types, indexes
- **Idempotent loads** with PostgreSQL upserts and transactions
- **CI/CD-style automation** with GitHub Actions cron schedules and encrypted secrets
- **Secrets management** across local, CI and cloud environments
- Building a **data dashboard** with Streamlit, including caching and parameterised queries

---

## Roadmap

- [ ] Daily aggregate view (min, max, total rain per city per day)
- [ ] Data quality checks: missing hours, out-of-range values
- [ ] Alerts (email or Discord) when wind gusts exceed a threshold
- [ ] More cities, configured from a file instead of code
- [ ] Unit tests with `pytest` for the transform and load logic
- [ ] Deploy the dashboard publicly on Streamlit Community Cloud

---

## Author

**Jenoah Gonsalves**

- 📧 Email: [jenoah2004@gmail.com](mailto:jenoah2004@gmail.com)
- 💼 LinkedIn: [linkedin.com/in/jenoah-gonsalves-106113146](https://www.linkedin.com/in/jenoah-gonsalves-106113146/)
- 🐙 GitHub: [@Jenzzzz7](https://github.com/Jenzzzz7)

*Weather data provided by [Open-Meteo.com](https://open-meteo.com/) under the CC BY 4.0 licence.*
